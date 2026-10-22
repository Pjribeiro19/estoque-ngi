"""
Patrimônio Carajás — Sistema de Gestão Patrimonial dos Projetos — NGI ICMBio Carajás — versão 1.0.

Login com usuários armazenados no PostgreSQL do patrimônio.
Cadastro de bens e cadastros auxiliares; movimentações e devoluções,
termos e anexos, inventário, baixa administrativa e relatórios CSV.
Perfis de acesso: Administrador, Operador e Consulta.
A estrutura das tabelas é preparada automaticamente ao iniciar.

CONFIGURAÇÃO NO RENDER:
- DATABASE_URL: conexão do banco exclusivo do patrimônio.
- SECRET_KEY: segredo aleatório de pelo menos 32 caracteres.

ADMINISTRADOR AUTOMÁTICO (Environment do Render):
- ADMIN_EMAIL: e-mail do administrador.
- ADMIN_NOME: nome do administrador.
- ADMIN_PASSWORD: senha de 12 a 128 caracteres.
Ao iniciar, cria ou sincroniza somente esse usuário. Remova ADMIN_PASSWORD
após confirmar o login para manter a senha gerenciada apenas no banco.

PREPARAÇÃO OPCIONAL, PELO SHELL DO RENDER:
    flask --app app iniciar-banco
    flask --app app criar-admin

Dependências: Pillow>=12,<13, qrcode>=8,<9, pillow-heif>=1,<2 e reportlab>=4,<5.
PUBLIC_URL: URL HTTPS pública usada nas plaquetas, nos links de senha e nos
  links de aceite eletrônico de termos (enviados pelo mesmo SMTP: EMAIL_*).
EMAIL_HOST=smtp.gmail.com; EMAIL_PORT=587 (STARTTLS) ou 465 (SSL).
EMAIL_USER=ngicarajasadm@gmail.com; EMAIL_PASSWORD=senha de app do Gmail.
Os nomes SMTP_HOST/PORT/USER/PASSWORD também são aceitos como alternativa.
Remova ADMIN_PASSWORD após o primeiro acesso: mantê-la redefinirá a senha a cada deploy.
Teste no Shell: flask --app app testar-email. No Render Free, SMTP é bloqueado.
Não há senha padrão ou cadastro público de administradores.
OPERAÇÃO 3.2:
- BACKUP_KEY: chave base64 de 32 bytes (flask --app app backup-chave).
- BACKUP_S3_BUCKET, BACKUP_S3_ACCESS_KEY_ID, BACKUP_S3_SECRET_ACCESS_KEY.
- BACKUP_S3_REGION (padrão us-east-1), BACKUP_S3_ENDPOINT opcional HTTPS.
- Rotina externa diária: flask --app app backup-enviar.
- BACKUP_EXIGIR_DIARIO=sim somente após o primeiro envio bem-sucedido.
- SENTRY_DSN opcional e MONITOR_TOKEN aleatório de pelo menos 32 caracteres.
- /health/ready usa Authorization: Bearer MONITOR_TOKEN, nunca chave na URL.
Backup inclui só dados do schema patrimonio. Não inclui código/Environment.
Guardar a chave e a versão do app.py em lugar separado é indispensável.
Restauração somente em banco novo vazio; não executar no banco de produção.
Uso sem internet ainda NÃO habilitado.
Não configurar esta aplicação com o banco do SIGAD.
ARQUIVOS DA PASTA static/ (devem estar no repositório, ao lado do app.py):
- static/identidade-visual/icmbio.png e unidades.png: logos da tela de login.
- static/vendor/jsQR.js (jsQR 1.4.0, licença Apache-2.0): leitor de QR Code.
"""

# ============================================================
# 1. IMPORTAÇÕES E CONFIGURAÇÕES
# ============================================================
import io
import base64
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from html import escape as html_escape
import json
import secrets
import warnings
import hashlib
import unicodedata
import hmac
import os
import re
import time
import csv
import qrcode
from urllib.parse import quote, urlsplit
from datetime import date, datetime, timedelta, timezone
from functools import wraps, lru_cache
from decimal import Decimal, InvalidOperation
from PIL import Image, ImageChops, ImageOps, ImageDraw, UnidentifiedImageError
from pypdf import PdfReader
from werkzeug.datastructures import FileStorage
from pillow_heif import register_heif_opener
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth, registerFont
from reportlab.pdfbase.ttfonts import TTFont
import reportlab
# Fontes incluídas no próprio ReportLab: PDF portátil para a gráfica.
registerFont(TTFont('NGI', os.path.join(os.path.dirname(reportlab.__file__), 'fonts', 'Vera.ttf')))
registerFont(TTFont('NGI-Bold', os.path.join(os.path.dirname(reportlab.__file__), 'fonts', 'VeraBd.ttf')))
register_heif_opener(thumbnails=False)
from jinja2 import ChoiceLoader, DictLoader

import click
from flask import (
    render_template,
    Flask,
    Response,
    flash,
    jsonify,
    abort,
    make_response,
    g,
    redirect,
    render_template_string,
    request,
    session,
    stream_with_context,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect, CSRFError
from sqlalchemy import MetaData, func, select, text, delete, inspect, or_, and_, case, cast, true
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
TESTE_LOCAL = os.environ.get("APP_ENV") == "test"
secret = os.environ.get("SECRET_KEY", "")
connection = os.environ.get("DATABASE_URL", "").strip()

if len(secret) < 32:
    raise RuntimeError("Configure SECRET_KEY no Render com pelo menos 32 caracteres.")
if not connection:
    raise RuntimeError("Configure DATABASE_URL com o banco exclusivo do patrimônio.")

# Normaliza o driver sem reconstruir ou exibir a senha.
try:
    database_url = make_url(connection)
except Exception:
    raise RuntimeError("DATABASE_URL inválida. Confira a URI no Render.") from None

if database_url.get_backend_name() in {"postgres", "postgresql"}:
    database_url = database_url.set(drivername="postgresql+psycopg")
    database_url = database_url.update_query_dict({"sslmode": "require"})
    engine_options = {
        "pool_pre_ping": True,
        "pool_size": 3,
        "max_overflow": 2,
        "pool_recycle": 300,
        "connect_args": {"connect_timeout": 10},
    }
elif TESTE_LOCAL and database_url.get_backend_name() == "sqlite":
    # Exclusivamente para os testes locais desta entrega.
    engine_options = {
        "execution_options": {"schema_translate_map": {"patrimonio": None}}
    }
else:
    raise RuntimeError("Esta aplicação exige PostgreSQL no ambiente de hospedagem.")

app.config.update(
    SECRET_KEY=secret,
    SQLALCHEMY_DATABASE_URI=database_url,
    SQLALCHEMY_ENGINE_OPTIONS=engine_options,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_NAME="ngi_patrimonio_session",
    SESSION_COOKIE_SECURE=not TESTE_LOCAL,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    SESSION_REFRESH_EACH_REQUEST=False,
    WTF_CSRF_TIME_LIMIT=3600,
    MAX_CONTENT_LENGTH=12 * 1024 * 1024,
)

# O Render termina o HTTPS no proxy imediatamente à frente da aplicação.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
db = SQLAlchemy(app, metadata=MetaData(schema="patrimonio"))
csrf = CSRFProtect(app)


# ============================================================
# 2. TABELAS DO LOGIN
# Schema exclusivo; não usa tabelas do SIGAD ou do Supabase Auth.
# ============================================================
class Usuario(db.Model):
    __tablename__ = "usuarios"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), nullable=False, unique=True, index=True)
    senha_hash = db.Column(db.String(512), nullable=False)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    perfil = db.Column(db.String(30), nullable=False, default="Administrador")
    versao_sessao = db.Column(db.Integer, nullable=False, default=1)
    criado_em = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    @property
    def leitura(self):
        # Perfis que só consultam: não cadastram, não movimentam e não alteram nada.
        return self.perfil in ('Consulta', 'Gestor de convênio')


class TentativaLogin(db.Model):
    __tablename__ = "tentativas_login"
    id = db.Column(db.Integer, primary_key=True)
    ip_hash = db.Column(db.String(64), nullable=False, index=True)
    email_hash = db.Column(db.String(64), nullable=False, index=True)
    instante = db.Column(db.BigInteger, nullable=False, index=True)


# Hash fictício usado para reduzir diferença de tempo entre e-mails existentes e inexistentes.
HASH_FICTICIO = generate_password_hash(os.urandom(32).hex())

# ============================================================
# 3. CADASTROS E PATRIMÔNIO — registros persistidos no banco
# ============================================================
# Os bens são lidos exclusivamente do banco. Não são inseridos dados fictícios.
class BaseLocal(db.Model):
    __tablename__ = "bases_locais"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(160), nullable=False)
    nome_chave = db.Column(db.String(160), nullable=False, unique=True)
    endereco = db.Column(db.String(300), nullable=False)
    latitude = db.Column(db.Numeric(10, 7), nullable=False)
    longitude = db.Column(db.Numeric(10, 7), nullable=False)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    revisao = db.Column(db.Integer, nullable=False, default=1)
    criado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class Convenio(db.Model):
    __tablename__ = "convenios"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(160), nullable=False)
    nome_chave = db.Column(db.String(160), nullable=False, unique=True)
    numero = db.Column(db.String(120), nullable=False, default="")
    financiador = db.Column(db.String(160), nullable=False, default="")
    objeto = db.Column(db.Text, nullable=False, default="")
    inicio = db.Column(db.Date, nullable=True)
    fim = db.Column(db.Date, nullable=True)
    valor = db.Column(db.Numeric(14, 2), nullable=True)
    gestor = db.Column(db.String(160), nullable=False, default="", server_default="")
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    revisao = db.Column(db.Integer, nullable=False, default=1)


class AuditoriaUsuario(db.Model):
    __tablename__ = "auditoria_usuarios"
    id = db.Column(db.Integer, primary_key=True)
    autor_id = db.Column(db.Integer, db.ForeignKey("patrimonio.usuarios.id"), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("patrimonio.usuarios.id"), nullable=False)
    acao = db.Column(db.String(160), nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class Categoria(db.Model):
    __tablename__='categorias'
    id=db.Column(db.Integer,primary_key=True)
    nome=db.Column(db.String(100),nullable=False)
    nome_chave=db.Column(db.String(100),nullable=False,unique=True)
    descricao=db.Column(db.String(500),nullable=False,default='')
    ativo=db.Column(db.Boolean,nullable=False,default=True)
    revisao=db.Column(db.Integer,nullable=False,default=1)


class Coordenacao(db.Model):
    __tablename__ = 'coordenacoes'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(160), nullable=False)
    nome_chave = db.Column(db.String(160), nullable=False, unique=True)
    sigla = db.Column(db.String(20), nullable=False)
    sigla_chave = db.Column(db.String(20), nullable=False, unique=True)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    revisao = db.Column(db.Integer, nullable=False, default=1)


class GestorConvenio(db.Model):
    # Convênios que um usuário do perfil "Gestor de convênio" acompanha.
    __tablename__ = 'gestores_convenios'
    usuario_id = db.Column(db.Integer, db.ForeignKey('patrimonio.usuarios.id'), primary_key=True)
    convenio_id = db.Column(db.Integer, db.ForeignKey('patrimonio.convenios.id'), primary_key=True, index=True)


class EntradaSigad(db.Model):
    # Um bem comprado pelo SIGAD que chegou e espera o tombamento (uma linha por unidade).
    __tablename__ = 'entradas_sigad'
    id = db.Column(db.Integer, primary_key=True)
    chave = db.Column(db.String(80), nullable=False, unique=True)
    sigad_solicitacao_id = db.Column(db.Integer, nullable=False, index=True)
    protocolo = db.Column(db.String(40), nullable=False)
    sigad_item_id = db.Column(db.Integer, nullable=False)
    unidade = db.Column(db.Integer, nullable=False, default=1)
    quantidade_total = db.Column(db.Integer, nullable=False, default=1)
    nome = db.Column(db.String(300), nullable=False)
    justificativa = db.Column(db.Text, nullable=False, default='')
    valor_unitario = db.Column(db.Numeric(14, 2), nullable=True)
    fornecedor = db.Column(db.String(300), nullable=False, default='')
    convenio_texto = db.Column(db.String(200), nullable=False, default='')
    convenio_id = db.Column(db.Integer, db.ForeignKey('patrimonio.convenios.id'), nullable=True)
    coordenacao_texto = db.Column(db.String(100), nullable=False, default='')
    coordenacao_id = db.Column(db.Integer, db.ForeignKey('patrimonio.coordenacoes.id'), nullable=True)
    solicitante = db.Column(db.String(200), nullable=False, default='')
    contato = db.Column(db.String(200), nullable=False, default='')
    data_compra = db.Column(db.Date, nullable=True)
    recebido_em = db.Column(db.Date, nullable=True)
    recebido_por = db.Column(db.String(200), nullable=False, default='')
    classificacao_justificativa = db.Column(db.Text, nullable=False, default='')
    status = db.Column(db.String(30), nullable=False, default='Aguardando tombamento', index=True)
    bem_id = db.Column(db.Integer, db.ForeignKey('patrimonio.bens.id'), nullable=True)
    motivo_descarte = db.Column(db.Text, nullable=False, default='')
    tratado_por = db.Column(db.Integer, db.ForeignKey('patrimonio.usuarios.id'), nullable=True)
    tratado_em = db.Column(db.DateTime(timezone=True), nullable=True)
    criado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class EntradaSigadNota(db.Model):
    # Nota fiscal enviada pelo SIGAD, uma por compra; copiada para cada bem no tombamento.
    __tablename__ = 'entradas_sigad_notas'
    sigad_solicitacao_id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(160), nullable=False)
    mime = db.Column(db.String(80), nullable=False)
    dados = db.Column(db.LargeBinary, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class Bem(db.Model):
    __tablename__ = "bens"
    __table_args__ = (
        db.UniqueConstraint("origem", "plaqueta_original", name="uq_bem_origem_plaqueta"),
        db.UniqueConstraint("marca", "serie", name="uq_bem_marca_serie"),
    )
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(160), nullable=False)
    descricao = db.Column(db.Text, nullable=False)
    marca = db.Column(db.String(100), nullable=False)
    modelo = db.Column(db.String(120), nullable=False)
    serie = db.Column(db.String(160), nullable=True)
    serie_excecao = db.Column(db.String(30), nullable=False, default="Informado")
    serie_justificativa = db.Column(db.Text, nullable=False, default="")
    plaqueta_original = db.Column(db.String(120), nullable=True)
    origem = db.Column(db.String(120), nullable=True)
    etiqueta_situacao = db.Column(db.String(30), nullable=False, default="Não verificada", server_default="Não verificada")
    numero_ngi = db.Column(db.String(40), unique=True, nullable=True)
    categoria_id = db.Column(db.Integer,db.ForeignKey("patrimonio.categorias.id"),nullable=True,index=True)
    categoria = db.Column(db.String(100),nullable=False,default="")
    coordenacao_id = db.Column(db.Integer, db.ForeignKey("patrimonio.coordenacoes.id"), nullable=True, index=True)
    coordenacao = db.Column(db.String(20), nullable=False, default="", server_default="")
    # Patrimônio = bem permanente controlado com plaqueta; Não é patrimônio = controle simples.
    classificacao = db.Column(db.String(30), nullable=False, default="Patrimônio", server_default="Patrimônio")
    classificacao_justificativa = db.Column(db.Text, nullable=False, default="", server_default="")
    convenio_id = db.Column(db.Integer, db.ForeignKey("patrimonio.convenios.id"), nullable=True, index=True)
    convenio = db.Column(db.String(160), nullable=False, index=True)
    base_id = db.Column(db.Integer, db.ForeignKey("patrimonio.bases_locais.id"), nullable=True, index=True)
    local = db.Column(db.String(160), nullable=False, index=True)
    endereco = db.Column(db.String(300), nullable=False)
    complemento = db.Column(db.String(200), nullable=False, default="")
    latitude = db.Column(db.Numeric(10, 7), nullable=True)
    longitude = db.Column(db.Numeric(10, 7), nullable=True)
    responsavel = db.Column(db.String(160), nullable=False)
    responsavel_contato = db.Column(db.String(160), nullable=False, default="")
    situacao = db.Column(db.String(30), nullable=False)
    conservacao = db.Column(db.String(30), nullable=False)
    data_aquisicao = db.Column(db.Date, nullable=True)
    valor = db.Column(db.Numeric(14, 2), nullable=True)
    aquisicao_justificativa = db.Column(db.Text, nullable=False, default="")
    nota_fiscal = db.Column(db.String(60), nullable=False, default="", server_default="")
    fornecedor = db.Column(db.String(160), nullable=False, default="", server_default="")
    # Como o bem chegou: Compra, Doação (ex.: doado pela Vale) ou Apreensão já destinada ao NGI
    forma_ingresso = db.Column(db.String(40), nullable=False, default="Compra", server_default="Compra")
    ingresso_detalhe = db.Column(db.String(200), nullable=False, default="", server_default="")
    observacoes = db.Column(db.Text, nullable=False, default="")
    tem_foto = db.Column(db.Boolean, nullable=False, default=False)
    conferido = db.Column(db.Boolean, nullable=False, default=False)
    encerrado = db.Column(db.Boolean, nullable=False, default=False, index=True)
    encerrado_em = db.Column(db.DateTime(timezone=True), nullable=True)
    criado_por = db.Column(db.Integer, db.ForeignKey("patrimonio.usuarios.id"), nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    atualizado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    revisao = db.Column(db.Integer, nullable=False, default=1)

    @property
    def nota_fiscal_anexada(self):
        return db.session.scalar(select(NotaFiscalBem.bem_id).where(NotaFiscalBem.bem_id == self.id)) is not None

    @property
    def patrimonio(self):
        if self.numero_ngi:
            return self.numero_ngi
        if self.plaqueta_original:
            return f"{self.plaqueta_original} · {self.origem}"
        return self.numero_ngi or "Sem plaqueta · A gerar"

    @property
    def tipo(self):
        return "box"

    def __getitem__(self, key):
        return getattr(self, key)


class FotoBem(db.Model):
    # Uma fotografia por bem, mantida no PostgreSQL para sobreviver aos deploys.
    # A tabela separada evita carregar os bytes nas consultas do painel.
    __tablename__ = "fotos_bens"
    bem_id = db.Column(db.Integer, db.ForeignKey("patrimonio.bens.id"), primary_key=True)
    dados = db.Column(db.LargeBinary, nullable=False)
    mime = db.Column(db.String(30), nullable=False, default="image/jpeg")


class NotaFiscalBem(db.Model):
    # Arquivo opcional da nota fiscal (PDF ou imagem), um por bem.
    __tablename__ = "notas_fiscais_bens"
    bem_id = db.Column(db.Integer, db.ForeignKey("patrimonio.bens.id"), primary_key=True)
    nome = db.Column(db.String(160), nullable=False)
    mime = db.Column(db.String(80), nullable=False)
    dados = db.Column(db.LargeBinary, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    autor_id = db.Column(db.Integer, db.ForeignKey("patrimonio.usuarios.id"), nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class EventoBem(db.Model):
    __tablename__ = "eventos_bens"
    id = db.Column(db.Integer, primary_key=True)
    bem_id = db.Column(db.Integer, db.ForeignKey("patrimonio.bens.id"), nullable=False, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("patrimonio.usuarios.id"), nullable=False)
    acao = db.Column(db.String(50), nullable=False)
    detalhes = db.Column(db.Text, nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class SequenciaPlaqueta(db.Model):
    __tablename__ = "sequencias_plaquetas"
    ano = db.Column(db.Integer, primary_key=True)
    ultimo = db.Column(db.Integer, nullable=False, default=0)


class OperacaoCadastro(db.Model):
    # Impede dois cadastros causados por clique duplo ou reenvio do formulário.
    __tablename__ = "operacoes_cadastro"
    token = db.Column(db.String(64), primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("patrimonio.usuarios.id"), nullable=False)
    bem_id = db.Column(db.Integer, db.ForeignKey("patrimonio.bens.id"), nullable=False)


# ============================================================
# OPERAÇÕES PATRIMONIAIS — registros preservados e auditáveis
# ============================================================
class Movimento(db.Model):
    __tablename__ = 'movimentos'
    id = db.Column(db.Integer, primary_key=True)
    bem_id = db.Column(db.Integer, db.ForeignKey('patrimonio.bens.id'), nullable=False, index=True)
    tipo = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(30), nullable=False, default='Pendente', index=True)
    origem = db.Column(db.JSON, nullable=False)
    destino = db.Column(db.JSON, nullable=False)
    revisao_bem = db.Column(db.Integer, nullable=False)
    motivo = db.Column(db.Text, nullable=False)
    referencia = db.Column(db.String(200), nullable=False, default='')
    previsao_retorno = db.Column(db.Date, nullable=True)
    retorno_de = db.Column(db.Integer, db.ForeignKey('patrimonio.movimentos.id'), nullable=True, index=True)
    devolvido_em = db.Column(db.DateTime(timezone=True), nullable=True)
    criado_por = db.Column(db.Integer, db.ForeignKey('patrimonio.usuarios.id'), nullable=False)
    criado_nome = db.Column(db.String(120), nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    concluido_por = db.Column(db.Integer, db.ForeignKey('patrimonio.usuarios.id'), nullable=True)
    concluido_em = db.Column(db.DateTime(timezone=True), nullable=True)
    motivo_cancelamento = db.Column(db.Text, nullable=False, default='')


class ProcessoBaixa(db.Model):
    __tablename__ = 'processos_baixa'
    id = db.Column(db.Integer, primary_key=True)
    bem_id = db.Column(db.Integer, db.ForeignKey('patrimonio.bens.id'), nullable=False, index=True)
    status = db.Column(db.String(30), nullable=False, default='Em análise', index=True)
    motivo = db.Column(db.String(60), nullable=False)
    justificativa = db.Column(db.Text, nullable=False)
    processo = db.Column(db.String(200), nullable=False)
    titularidade = db.Column(db.String(160), nullable=False)
    destinacao = db.Column(db.String(300), nullable=False)
    avaliacao = db.Column(db.String(300), nullable=False, default='')
    retrato = db.Column(db.JSON, nullable=False)
    criado_por = db.Column(db.Integer, db.ForeignKey('patrimonio.usuarios.id'), nullable=False)
    criado_nome = db.Column(db.String(120), nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    decisao = db.Column(db.Text, nullable=False, default='')
    autoridade = db.Column(db.String(160), nullable=False, default='')
    autorizacao = db.Column(db.String(300), nullable=False, default='')
    concluido_por = db.Column(db.Integer, db.ForeignKey('patrimonio.usuarios.id'), nullable=True)
    concluido_em = db.Column(db.DateTime(timezone=True), nullable=True)


class Documento(db.Model):
    __tablename__ = 'documentos'
    id = db.Column(db.Integer, primary_key=True)
    bem_id = db.Column(db.Integer, db.ForeignKey('patrimonio.bens.id'), nullable=True, index=True)
    movimento_id = db.Column(db.Integer, db.ForeignKey('patrimonio.movimentos.id'), nullable=True, unique=True)
    solicitacao_baixa_id = db.Column(db.Integer, db.ForeignKey('patrimonio.processos_baixa.id'), nullable=True, unique=True)
    baixa_id = db.Column(db.Integer, db.ForeignKey('patrimonio.processos_baixa.id'), nullable=True, unique=True)
    tipo = db.Column(db.String(80), nullable=False)
    dados = db.Column(db.JSON, nullable=False)
    resumo = db.Column(db.String(300), nullable=False)
    integridade = db.Column(db.String(64), nullable=False)
    autor_id = db.Column(db.Integer, db.ForeignKey('patrimonio.usuarios.id'), nullable=False)
    autor_nome = db.Column(db.String(120), nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class AnexoDocumento(db.Model):
    __tablename__ = 'anexos_documentos'
    id = db.Column(db.Integer, primary_key=True)
    documento_id = db.Column(db.Integer, db.ForeignKey('patrimonio.documentos.id'), nullable=False, index=True)
    nome = db.Column(db.String(160), nullable=False)
    mime = db.Column(db.String(80), nullable=False)
    dados = db.Column(db.LargeBinary, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    autor_id = db.Column(db.Integer, db.ForeignKey('patrimonio.usuarios.id'), nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class AceiteTermo(db.Model):
    # Aceite eletrônico de termo por link único enviado ao e-mail do responsável.
    # O token nunca é salvo: guarda-se só o HMAC. Cada envio é um registro (histórico).
    __tablename__ = 'aceites_termos'
    id = db.Column(db.Integer, primary_key=True)
    documento_id = db.Column(db.Integer, db.ForeignKey('patrimonio.documentos.id'), nullable=False, index=True)
    email = db.Column(db.String(254), nullable=False)
    nome_destinatario = db.Column(db.String(160), nullable=False, default='')
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    status = db.Column(db.String(20), nullable=False, default='Pendente')
    integridade_documento = db.Column(db.String(64), nullable=False)
    enviado_por = db.Column(db.Integer, db.ForeignKey('patrimonio.usuarios.id'), nullable=False)
    enviado_por_nome = db.Column(db.String(120), nullable=False, default='')
    criado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    expira_em = db.Column(db.BigInteger, nullable=False)
    visualizado_em = db.Column(db.DateTime(timezone=True), nullable=True)
    respondido_em = db.Column(db.DateTime(timezone=True), nullable=True)
    nome_digitado = db.Column(db.String(160), nullable=False, default='')
    motivo_recusa = db.Column(db.Text, nullable=False, default='')
    ip = db.Column(db.String(64), nullable=False, default='')
    user_agent = db.Column(db.String(300), nullable=False, default='')
    comprovante = db.Column(db.String(64), nullable=False, default='')

    @property
    def situacao(self):
        if self.status == 'Pendente' and self.expira_em <= int(time.time()):
            return 'Expirado'
        return self.status

    @property
    def expira_data(self):
        return datetime.fromtimestamp(self.expira_em, timezone.utc)


class AssinaturaDocumento(db.Model):
    # Assinatura eletrônica do emitente, feita dentro do sistema com login + senha
    # digitada de novo. Uma por documento; guarda o código de integridade do
    # documento no momento da assinatura e um comprovante (SHA-256).
    __tablename__ = 'assinaturas_documentos'
    id = db.Column(db.Integer, primary_key=True)
    documento_id = db.Column(db.Integer, db.ForeignKey('patrimonio.documentos.id'), nullable=False, unique=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('patrimonio.usuarios.id'), nullable=False)
    nome = db.Column(db.String(120), nullable=False)
    perfil = db.Column(db.String(30), nullable=False, default='')
    declaracao = db.Column(db.Text, nullable=False)
    integridade_documento = db.Column(db.String(64), nullable=False)
    ip = db.Column(db.String(64), nullable=False, default='')
    user_agent = db.Column(db.String(300), nullable=False, default='')
    assinado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    comprovante = db.Column(db.String(64), nullable=False)


class TermoBem(db.Model):
    # Bens cobertos por um termo com vários bens (um termo e um aceite para o kit).
    __tablename__ = 'termos_bens'
    documento_id = db.Column(db.Integer, db.ForeignKey('patrimonio.documentos.id'), primary_key=True)
    bem_id = db.Column(db.Integer, db.ForeignKey('patrimonio.bens.id'), primary_key=True, index=True)


class CampanhaInventario(db.Model):
    __tablename__ = 'inventarios'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(160), nullable=False)
    prazo = db.Column(db.Date,nullable=True)
    comissao = db.Column(db.String(1000),nullable=False,default='')
    referencia = db.Column(db.String(200), nullable=False, default='')
    base_id = db.Column(db.Integer, db.ForeignKey('patrimonio.bases_locais.id'), nullable=True)
    convenio_id = db.Column(db.Integer, db.ForeignKey('patrimonio.convenios.id'), nullable=True)
    local = db.Column(db.String(160), nullable=False)
    status = db.Column(db.String(30), nullable=False, default='Aberto', index=True)
    autor_id = db.Column(db.Integer, db.ForeignKey('patrimonio.usuarios.id'), nullable=False)
    criado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    encerrado_em = db.Column(db.DateTime(timezone=True), nullable=True)
    encerrado_por = db.Column(db.Integer, db.ForeignKey('patrimonio.usuarios.id'), nullable=True)


class ItemInventario(db.Model):
    __tablename__ = 'itens_inventario'
    __table_args__ = (db.UniqueConstraint('inventario_id','bem_id',name='uq_inventario_bem'),)
    id = db.Column(db.Integer, primary_key=True)
    inventario_id = db.Column(db.Integer, db.ForeignKey('patrimonio.inventarios.id'), nullable=False, index=True)
    bem_id = db.Column(db.Integer, db.ForeignKey('patrimonio.bens.id'), nullable=False, index=True)
    retrato = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(30), nullable=False, default='Pendente', index=True)
    observacao = db.Column(db.Text, nullable=False, default='')
    conferente_id = db.Column(db.Integer, db.ForeignKey('patrimonio.usuarios.id'), nullable=True)
    conferente_nome = db.Column(db.String(120), nullable=False, default='')
    conferido_em = db.Column(db.DateTime(timezone=True), nullable=True)
    revisao = db.Column(db.Integer, nullable=False, default=1)


class LinkCampo(db.Model):
    # Link de equipe para conferir um inventário no campo, sem login e sem internet.
    __tablename__ = 'links_campo'
    id = db.Column(db.Integer, primary_key=True)
    inventario_id = db.Column(db.Integer, db.ForeignKey('patrimonio.inventarios.id'), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    rotulo = db.Column(db.String(120), nullable=False, default='')
    local = db.Column(db.String(160), nullable=False, default='')
    criado_por = db.Column(db.Integer, db.ForeignKey('patrimonio.usuarios.id'), nullable=False)
    criado_por_nome = db.Column(db.String(120), nullable=False, default='')
    criado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    expira_em = db.Column(db.BigInteger, nullable=False)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    envios = db.Column(db.Integer, nullable=False, default=0)
    ultimo_envio = db.Column(db.DateTime(timezone=True), nullable=True)

    @property
    def vencido(self):
        return self.expira_em <= int(time.time())

    @property
    def expira_data(self):
        return datetime.fromtimestamp(self.expira_em, timezone.utc)


class AchadoCampo(db.Model):
    # Bem encontrado no campo que não está na lista do inventário (sem plaqueta ou de outro local).
    __tablename__ = 'achados_campo'
    __table_args__ = (db.UniqueConstraint('link_id', 'cliente_id', name='uq_achado_link_cliente'),)
    id = db.Column(db.Integer, primary_key=True)
    inventario_id = db.Column(db.Integer, db.ForeignKey('patrimonio.inventarios.id'), nullable=False, index=True)
    link_id = db.Column(db.Integer, db.ForeignKey('patrimonio.links_campo.id'), nullable=False)
    cliente_id = db.Column(db.String(40), nullable=False)
    descricao = db.Column(db.Text, nullable=False)
    codigo = db.Column(db.String(300), nullable=False, default='')
    pessoa = db.Column(db.String(120), nullable=False, default='')
    criado_em = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class OperacaoPatrimonial(db.Model):
    __tablename__ = 'operacoes_patrimoniais'
    token = db.Column(db.String(64), primary_key=True)
    autor_id = db.Column(db.Integer, db.ForeignKey('patrimonio.usuarios.id'), nullable=False)
    destino = db.Column(db.String(240), nullable=False)


class DestinacaoConvenio(db.Model):
    __tablename__='destinacoes_convenios'
    __table_args__=(db.UniqueConstraint('convenio_id','bem_id',name='uq_destinacao_convenio_bem'),)
    id=db.Column(db.Integer,primary_key=True)
    convenio_id=db.Column(db.Integer,db.ForeignKey('patrimonio.convenios.id'),nullable=False,index=True)
    bem_id=db.Column(db.Integer,db.ForeignKey('patrimonio.bens.id'),nullable=False,index=True)
    destino=db.Column(db.String(80),nullable=False)
    justificativa=db.Column(db.Text,nullable=False)
    referencia=db.Column(db.String(300),nullable=False)
    autor_id=db.Column(db.Integer,db.ForeignKey('patrimonio.usuarios.id'),nullable=False)
    autor_nome=db.Column(db.String(120),nullable=False)
    atualizado_em=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc))
    revisao=db.Column(db.Integer,nullable=False,default=1)


# 4. PAINEL VISUAL PRESERVADO
TEMPLATE = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Patrimônio Carajás · NGI ICMBio Carajás</title>
{% if modulo_template=='inv_detalhe' %}<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;650;700&amp;family=Geist+Mono:wght@400;500;600&amp;display=swap" rel="stylesheet">{% endif %}
<style>
:root {
    --green:#153f32;
    --accent:#28694f;
    --bg:#f5f6f3;
    --ink:#182820;
    --muted:#718078;
    --line:#e3e8e2;
}

* {
    box-sizing:border-box;
}

body {
    margin:0;
    background:var(--bg);
    color:var(--ink);
    font:14px system-ui,-apple-system,'Segoe UI',sans-serif;
}

button,input,select {
    font:inherit;
}

button,a,select {
    touch-action:manipulation;
}

button {
    cursor:pointer;
}

a {
    color:inherit;
    text-decoration:none;
}

svg {
    width:21px;
    height:21px;
    fill:none;
    stroke:currentColor;
    stroke-width:1.6;
    stroke-linecap:round;
    stroke-linejoin:round;
    flex-shrink:0;
}

button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible {
    outline:3px solid #64a889;
    outline-offset:3px;
}

.sidebar {
    position:fixed;
    inset:0 auto 0 0;
    width:238px;
    background:#13392d;
    color:#d7e5dc;
    padding:32px 18px;
    display:flex;
    flex-direction:column;
    z-index:20;
}

.brand {
    display:flex;
    align-items:center;
    gap:12px;
    padding:0 10px 30px;
}

.brand svg {
    width:37px;
    height:37px;
    color:#99bd9c;
}

.brand strong {
    font-size:23px;
    color:white;
    letter-spacing:-.7px;
}

.brand small {
    display:block;
    font-size:9px;
    letter-spacing:2px;
    margin-top:6px;
}

.nav {
    display:grid;
    gap:7px;
}

.nav a {
    display:flex;
    gap:13px;
    align-items:center;
    padding:13px 15px;
    border-radius:7px;
}

.nav a.active {
    background:#ffffff17;
    color:white;
}

.nav a:hover {
    background:#ffffff10;
}

.sidefoot {
    margin-top:auto;
    padding:20px 12px;
    color:#9db7a8;
    font-size:12px;
}

.sideart {
    margin-top:40px;
    opacity:.2;
    overflow:hidden;
}

.sideart svg {
    width:190px;
    height:140px;
    stroke-width:.6;
}

.shell {
    margin-left:238px;
}

.top {
    height:78px;
    background:#fff;
    border-bottom:1px solid var(--line);
    display:flex;
    align-items:center;
    justify-content:space-between;
    padding:0 38px;
    gap:20px;
}

.crumb {
    color:var(--muted);
    font-size:13px;
}

.profile {
    display:flex;
    align-items:center;
    gap:10px;
}

.avatar {
    background:var(--green);
    color:#fff;
    border-radius:50%;
    width:37px;
    height:37px;
    display:grid;
    place-items:center;
}

.profile small {
    display:block;
    color:var(--muted);
    font-size:11px;
}

.mobile {
    display:none;
}

main {
    max-width:1550px;
    margin:auto;
    padding:32px 38px;
}

h1 {
    font-size:30px;
    letter-spacing:-1px;
    margin:0 0 7px;
}

h2 {
    font-size:16px;
    margin:0;
}

p {
    color:var(--muted);
    line-height:1.6;
}

.intro {
    display:flex;
    justify-content:space-between;
    align-items:center;
    gap:20px;
    margin-bottom:24px;
}

.intro p {
    margin:0;
}

.actions {
    display:flex;
    gap:9px;
    flex-wrap:wrap;
}

.btn {
    border:1px solid #d5dfd7;
    border-radius:6px;
    background:white;
    padding:11px 15px;
    display:inline-flex;
    align-items:center;
    gap:8px;
    color:var(--green);
}

.primary {
    background:var(--green);
    border-color:var(--green);
    color:white;
}

.demo {
    display:inline-block;
    font-size:11px;
    background:#e8eee8;
    color:#53715f;
    padding:5px 8px;
    border-radius:4px;
    margin-bottom:12px;
}

.filters {
    display:flex;
    gap:12px;
    padding:13px;
    background:white;
    border:1px solid var(--line);
    border-radius:8px;
    margin-bottom:18px;
}

.filters input,.filters select {
    background:#fafbf9;
    border:1px solid var(--line);
    border-radius:5px;
    padding:10px;
    min-width:0;
    color:#43574a;
}

.filters input {
    flex:2;
}

.filters select {
    flex:1;
}

.stats {
    display:grid;
    grid-template-columns:repeat(4,1fr);
    gap:15px;
    margin-bottom:20px;
}

.stat,.panel {
    background:#fff;
    border:1px solid var(--line);
    border-radius:9px;
    box-shadow:0 3px 12px #183c2703;
}

.stat {
    padding:21px;
    display:flex;
    gap:14px;
}

.stat>svg {
    color:var(--accent);
    background:#edf4ee;
    padding:9px;
    box-sizing:content-box;
    border-radius:9px;
}

.stat span {
    color:#6c786f;
    font-size:12px;
}

.stat strong {
    display:block;
    font-size:27px;
    letter-spacing:-.8px;
    margin:7px 0;
}

.stat small {
    font-size:11px;
    color:var(--muted);
}

.middle {
    display:grid;
    grid-template-columns:1.3fr 1fr;
    gap:18px;
    margin-bottom:20px;
}

.panel {
    padding:23px;
}

.panelhead {
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:12px;
    margin-bottom:20px;
}

.panelhead p {
    margin:6px 0 0;
    font-size:12px;
}

.barrow {
    display:grid;
    grid-template-columns:96px 1fr 24px;
    gap:15px;
    align-items:center;
    margin:21px 0;
    font-size:12px;
}

.track {
    background:#f0f3ef;
    height:16px;
    border-radius:3px;
    overflow:hidden;
}

.fill {
    height:100%;
    background:#397453;
    border-radius:3px;
}

.priority {
    display:flex;
    gap:13px;
    padding:16px 0;
    border-bottom:1px solid #edf0eb;
    align-items:center;
}

.priority:last-child {
    border:0;
}

.priority svg {
    color:#98651e;
}

.priority small {
    display:block;
    color:var(--muted);
    margin-top:5px;
    font-size:12px;
}

.priority strong {
    font-size:13px;
}

.switch {
    display:flex;
    border:1px solid var(--line);
    padding:3px;
    border-radius:6px;
}

.switch button {
    border:0;
    background:white;
    padding:7px 12px;
    border-radius:4px;
    color:var(--muted);
}

.switch button.active {
    background:var(--green);
    color:white;
}

.tablewrap {
    overflow:auto;
}

table {
    border-collapse:collapse;
    width:100%;
    text-align:left;
    font-size:12px;
}

th {
    font-weight:500;
    color:var(--muted);
    background:#f6f8f5;
    white-space:nowrap;
}

td,th {
    padding:14px 12px;
    border-bottom:1px solid #edf0eb;
}

td small {
    display:block;
    color:var(--muted);
    margin-top:5px;
}

.asset {
    display:flex;
    gap:12px;
    align-items:center;
    min-width:215px;
}

.thumb {
    width:39px;
    height:39px;
    background:#edf2ed;
    border-radius:6px;
    display:grid;
    place-items:center;
    color:#486a55;
}

.badge {
    display:inline-block;
    padding:5px 9px;
    border-radius:20px;
    font-size:11px;
    background:#e6f2e9;
    color:#357451;
    white-space:nowrap;
}

.badge.field {
    background:#eaf1fb;
    color:#326994;
}

.badge.warn {
    background:#fff3df;
    color:#936322;
}

.detail {
    background:none;
    border:0;
    text-align:left;
    padding:0;
    color:var(--ink);
    cursor:pointer;
}

.detail:hover {
    text-decoration:underline;
}

.cards {
    display:grid;
    grid-template-columns:repeat(3,1fr);
    gap:15px;
}

.card {
    border:1px solid var(--line);
    border-radius:8px;
    padding:20px;
}

.card .thumb {
    margin-bottom:15px;
    width:48px;
    height:48px;
}

.card p {
    font-size:12px;
}

.count {
    font-size:11px;
    color:var(--muted);
    margin-top:18px;
}

.empty {
    text-align:center;
    padding:35px;
    color:var(--muted);
}

footer {
    font-size:11px;
    color:var(--muted);
    display:flex;
    justify-content:space-between;
    padding-top:24px;
}

.back {
    font-size:12px;
    color:var(--accent);
}

.facts {
    display:grid;
    grid-template-columns:repeat(2,1fr);
    gap:24px;
}

.facts dt {
    color:var(--muted);
    font-size:12px;
}

.facts dd {
    margin:7px 0 0;
    font-weight:600;
}

dialog {
    border:1px solid var(--line);
    border-radius:12px;
    max-width:440px;
    padding:28px;
    color:var(--ink);
}

dialog::backdrop {
    background:#112a2266;
}

dialog button {
    margin-top:12px;
}

[hidden] {
    display:none!important;
}

@media(min-width:1500px) {
    main {
        padding-top:40px;
    }

    .stat strong {
        font-size:30px;
    }

    .panel {
        padding:26px;
    }

}

@media(max-width:1150px) {
    .sidebar {
        width:210px;
    }

    .shell {
        margin-left:210px;
    }

    main {
        padding:26px 24px;
    }

    .top {
        padding:0 24px;
    }

    .stats {
        grid-template-columns:repeat(2,1fr);
    }

    .intro {
        align-items:flex-start;
        flex-direction:column;
    }

    .middle {
        grid-template-columns:1fr;
    }

    .cards {
        grid-template-columns:repeat(2,1fr);
    }

}

@media(max-width:700px) {
    .sidebar {
        transform:translateX(-100%);
        width:245px;
        transition:transform .2s;
    }

    .sidebar.open {
        transform:translateX(0);
    }

    .shell {
        margin:0;
    }

    .mobile {
        display:inline-flex;
    }

    .top {
        height:65px;
        padding:0 18px;
    }

    .crumb {
        display:none;
    }

    .profile {
        font-size:12px;
    }

    .profile small {
        font-size:10px;
    }

    main {
        padding:23px 16px;
    }

    h1 {
        font-size:25px;
    }

    .filters {
        flex-direction:column;
    }

    .filters input,.filters select {
        width:100%;
    }

    .stats {
        gap:10px;
    }

    .stat {
        padding:15px;
        gap:8px;
    }

    .stat>svg {
        display:none;
    }

    .stat strong {
        font-size:23px;
    }

    .stat span {
        font-size:11px;
    }

    .middle {
        gap:14px;
    }

    .panel {
        padding:18px;
    }

    .panelhead {
        flex-wrap:wrap;
    }

    .cards {
        grid-template-columns:1fr;
    }

    .facts {
        grid-template-columns:1fr;
    }

    footer {
        gap:12px;
    }

    .actions .btn {
        padding:10px;
    }

    .barrow {
        grid-template-columns:85px 1fr 20px;
    }

}

/* REFINAMENTO VISUAL — VERSÃO 0.2 */
:root {
    --green:#153e30;
    --accent:#367557;
    --bg:#f6f7f4;
    --ink:#1c2922;
    --muted:#727e76;
    --line:#e4e9e2;
}

body {
    -webkit-font-smoothing:antialiased;
}

.sidebar {
    width:224px;
    padding:27px 16px 18px;
    background:#123b2d;
    overflow-y:auto;
}

.brand {
    gap:10px;
    padding:0 8px 30px;
}

.brand strong {
    font-size:22px;
    font-weight:650;
}

.brand small {
    font-size:8px;
    letter-spacing:1.8px;
}

.nav {
    gap:5px;
}

.nav a {
    padding:12px;
    font-size:13px;
    border-radius:6px;
    transition:background-color .15s;
}

.nav a.active {
    background:#ffffff16;
    box-shadow:inset 3px 0 0 #95bfa1;
}

.nav svg {
    width:18px;
    height:18px;
}

.sideart {
    margin-top:30px;
    opacity:.12;
}

.sidefoot {
    font-size:10px;
    line-height:1.7;
}

.shell {
    margin-left:224px;
}

.top {
    height:68px;
    padding:0 30px;
}

.profile {
    font-size:12px;
}

.avatar {
    width:34px;
    height:34px;
    font-size:12px;
}

.btn.mobile {
    display:none;
}

main {
    max-width:1600px;
    padding:26px 30px;
}

h1 {
    font-size:28px;
    font-weight:650;
    letter-spacing:-.9px;
}

h2 {
    font-size:15px;
    font-weight:650;
    letter-spacing:-.2px;
}

.intro {
    margin-bottom:22px;
}

.intro p {
    font-size:13px;
}

.demo {
    margin-bottom:15px;
    padding:5px 8px;
    background:#edf1eb;
    color:#657665;
    font-size:10px;
}

.btn {
    padding:10px 14px;
    border-radius:6px;
    font-size:12px;
    font-weight:550;
    transition:background-color .15s,border-color .15s;
}

.btn:hover {
    background:#f1f5ef;
    border-color:#b9cabb;
}

.btn.primary:hover {
    background:#20533e;
    border-color:#20533e;
}

.btn svg {
    width:17px;
    height:17px;
}

.filters {
    padding:11px;
    gap:10px;
    margin-bottom:16px;
}

.filters input,.filters select {
    min-height:40px;
    padding:10px 12px;
    font-size:12px;
}

.filters input::placeholder {
    color:#88928b;
}

.stats {
    gap:14px;
    margin-bottom:18px;
    grid-template-columns:repeat(4,minmax(0,1fr));
}

.stat {
    padding:19px 16px;
    gap:12px;
    align-items:flex-start;
    min-width:0;
}

.stat>div {
    min-width:0;
}

.stat>svg {
    width:19px;
    height:19px;
    padding:9px;
    border-radius:8px;
}

.stat span {
    font-size:11px;
}

.stat strong {
    font-size:clamp(22px,1.8vw,29px);
    font-weight:650;
    letter-spacing:-.8px;
    line-height:1.2;
    margin:8px 0 7px;
    overflow-wrap:anywhere;
    font-variant-numeric:tabular-nums;
}

.stat small {
    font-size:10px;
    line-height:1.5;
}

.panel,.stat {
    border-radius:8px;
    box-shadow:0 2px 8px #173b2603;
}

.middle {
    grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);
    gap:16px;
    margin-bottom:18px;
}

.panel {
    padding:21px;
    min-width:0;
}

.panelhead {
    margin-bottom:16px;
}

.barrow {
    margin:19px 0;
}

.track {
    height:14px;
    background:#f0f3ed;
}

.fill {
    background:#447d5c;
}

.priority {
    padding:13px 0;
}

.priority strong {
    font-size:12px;
    font-weight:600;
}

.priority small {
    font-size:11px;
    line-height:1.5;
}

.priority svg {
    width:18px;
    height:18px;
}

th {
    background:#f7f8f5;
    font-size:11px;
}

td,th {
    padding:12px 11px;
}

tbody tr {
    transition:background-color .15s;
}

tbody tr:hover {
    background:#f8faf6;
}

.asset strong {
    font-size:12px;
    font-weight:600;
}

.thumb {
    background:#edf2ea;
    border:1px solid #e5ece1;
}

.badge {
    padding:5px 9px;
    font-size:10px;
    font-weight:500;
}

.switch button {
    font-size:11px;
    padding:7px 12px;
}

.card {
    padding:18px;
    min-width:0;
    transition:border-color .15s,box-shadow .15s;
}

.card:hover {
    border-color:#bacfbe;
    box-shadow:0 4px 14px #183c2708;
}

footer {
    padding-top:20px;
    font-size:10px;
}

.menu-overlay {
    display:none;
}

@media(max-width:1150px) {
    .sidebar {
        width:210px;
    }

    .shell {
        margin-left:210px;
    }

    main {
        padding:24px;
    }

    .top {
        padding:0 24px;
    }

    .middle {
        grid-template-columns:1fr;
    }

    .stats {
        grid-template-columns:repeat(2,minmax(0,1fr));
    }

}

@media(max-width:700px) {
    .sidebar {
        width:245px;
    }

    .shell {
        margin-left:0;
    }

    .btn.mobile {
        display:inline-flex;
        min-height:44px;
    }

    .top {
        height:64px;
        padding:0 16px;
    }

    main {
        padding:22px 16px;
    }

    h1 {
        font-size:25px;
        line-height:1.18;
    }

    .intro {
        gap:16px;
    }

    .intro p {
        font-size:12px;
    }

    .actions {
        width:100%;
    }

    .actions .btn {
        min-height:44px;
        justify-content:center;
        flex:1;
    }

    .filters input,.filters select {
        min-height:44px;
        font-size:16px;
    }

    .stat {
        padding:16px 13px;
    }

    .stat strong {
        font-size:23px;
    }

    .stat span {
        font-size:11px;
    }

    .panel {
        padding:18px;
    }

    .switch button {
        min-height:38px;
    }

    .card .detail {
        display:inline-block;
        padding:5px 0;
    }

    footer {
        flex-direction:column;
        gap:6px;
    }

    .sidebar {
        z-index:30;
    }

    .menu-overlay.open {
        display:block;
        position:fixed;
        inset:0;
        z-index:25;
        border:0;
        background:#112a2266;
    }

}

@media(prefers-reduced-motion:reduce) {
    *,*::before,*::after {
        transition:none!important;
    }

}

/* Cadastro e ficha: mesma linguagem visual do painel. */
.feedback{padding:16px 20px;background:#eaf4ef;border:1px solid #c7ded1;border-radius:12px;margin:18px 0;color:#174c37}
.form-grid,.ficha-grid{display:grid;grid-template-columns:1fr 1fr;gap:24px;align-items:start}
.form-section{padding:26px;margin-bottom:22px;background:white;border:1px solid var(--line,#e2e7e3);border-radius:16px}
.form-section h2{margin:0 0 8px}.form-section>p{color:var(--muted);margin-bottom:24px;font-size:14px}
.fields{display:grid;grid-template-columns:1fr 1fr;gap:20px}.wide{grid-column:1/-1}
.field label{display:block;font-size:13px;font-weight:650;margin-bottom:9px;color:#263f34}
.field input,.field textarea,.field select{width:100%;border:1px solid #cbd6ce;border-radius:9px;background:#fff;padding:12px;font:inherit;font-size:14px;box-sizing:border-box;color:#233b30}
.field input:focus,.field textarea:focus,.field select:focus{outline:2px solid #94b7a1;outline-offset:2px}.field textarea{min-height:100px;resize:vertical}
.field small,.hint{display:block;color:#63766a;font-size:12px;line-height:1.6;margin-top:7px}
.checkline{display:flex;gap:10px;align-items:center;font-size:14px}.checkline input{width:18px;height:18px}
.form-actions{display:flex;justify-content:flex-end;gap:12px;padding:8px 0 28px}.btn{text-decoration:none}
.erros{background:#fff0eb;color:#883c26;border:1px solid #e8bdad;padding:18px 24px;border-radius:12px;margin-bottom:24px}.erros li{margin:8px 0}
.callout{background:#f0f5f1;border:1px solid #d7e4db;border-radius:12px;padding:20px;margin:20px 0}.callout p{font-size:14px;line-height:1.6;color:#51675a}
.foto-ficha{display:block;max-height:370px;width:100%;object-fit:contain;border-radius:12px;background:#f4f6f3}
.sem-foto{padding:65px 20px;text-align:center;color:#6d8073;background:#f0f4ef;border-radius:12px}
.thumb img{width:100%;height:100%;object-fit:cover;border-radius:inherit}.card .thumb{overflow:hidden}.texto-longo{white-space:pre-wrap;overflow-wrap:anywhere}.facts dd{overflow-wrap:anywhere}
.historico{border-left:2px solid #abc4b3;padding:8px 16px;margin:16px 0}.historico small{display:block;color:#687d70;font-size:12px;margin-top:5px}
.photo-preview{display:block;max-width:100%;max-height:240px;object-fit:contain;margin:16px auto;border-radius:10px}.photo-preview[hidden]{display:none}
@media(max-width:950px){.form-grid,.ficha-grid{grid-template-columns:1fr}}@media(max-width:550px){.fields{grid-template-columns:1fr}.form-section{padding:20px}.form-actions{flex-wrap:wrap}.form-actions .btn{flex:1;text-align:center}.field input,.field textarea,.field select{font-size:16px}}

/* Uma página, uma confirmação. Os campos continuam visíveis durante o preenchimento. */
.single-heading{display:flex;align-items:center;justify-content:space-between;gap:20px;margin:6px 0 24px}.single-heading h1{font-size:29px;margin:10px 0 6px;letter-spacing:-.9px}.single-heading p{font-size:14px;color:var(--muted);margin:0}.single-heading>small{font-size:11px;color:#768479}
.single-layout{display:grid;grid-template-columns:minmax(0,1fr) 285px;gap:22px;align-items:start}.single-main{min-width:0}.single-main .form-section,.single-aside .form-section{padding:22px;border-radius:12px;margin-bottom:18px}.single-main h2,.single-aside h2{font-size:17px;letter-spacing:-.3px}.single-main .form-section>p,.section-top p,.single-aside .form-section>p{font-size:12px;line-height:1.5;margin:6px 0 18px;color:#718074}.single-main .fields{gap:14px 18px}.single-main .field label{font-size:12px;margin-bottom:6px}.single-main .field input,.single-main .field select{font-size:13px;min-height:39px;padding:9px 11px;border-radius:7px}.single-main .field textarea{font-size:13px;min-height:67px;padding:10px 11px;border-radius:7px}.single-main .field small{font-size:10px;line-height:1.5}.single-divider{padding-top:18px;margin-top:18px;border-top:1px solid #e6ebe5}.single-divider h3{font-size:14px;margin:0 0 14px}.single-aside{position:sticky;top:88px}.single-aside input[type=file]{font-size:11px;padding:10px 7px}.single-aside .field label{font-size:12px}.photo-box{background:#f2f5ef;border-radius:9px}.single-aside .photo-preview{max-height:225px;margin:12px auto}.photo-tip{font-size:10px;line-height:1.5;color:#7a897c;text-align:center}.single-aside .checkline{font-size:11px}.summary-box .eyebrow{font-size:9px;letter-spacing:1.5px;color:#758674}.summary-box h3{font-size:16px;margin:13px 0 18px;overflow-wrap:anywhere}.summary-box dt{font-size:10px;color:#819080;margin:12px 0 5px}.summary-box dd{font-size:12px;margin:0;color:#31503c;overflow-wrap:anywhere}.summary-box p{font-size:11px;color:#738474;line-height:1.6;margin-top:20px}.section-top{display:flex;align-items:flex-start;justify-content:space-between;gap:15px}.section-top h2{margin:0}.section-top p{margin-bottom:18px}.text-action{border:0;background:none;color:#236145;font:600 12px system-ui;text-decoration:none;cursor:pointer;white-space:nowrap;padding:4px 0}.text-action:hover{text-decoration:underline}.base-details{padding:14px 16px;border-radius:8px;background:#f0f5ef;border:1px solid #e0e8de;font-size:12px}.base-details[hidden]{display:none}.base-details strong{display:block;margin:7px 0;color:#38543d;font-weight:500}.base-details>span:not(.base-tag){font-size:11px;color:#70836f;display:block}.base-details a{display:inline-block;color:#236145;margin-top:10px;font-size:11px}.base-tag{font-size:9px;letter-spacing:1px;color:#6d886e;text-transform:uppercase}
.single-actions{position:sticky;bottom:0;background:rgba(249,250,247,.98);border-top:1px solid #dfe6dc;z-index:15;padding:15px 0;display:flex;justify-content:space-between;align-items:center;gap:15px}.single-actions>span{font-size:11px;color:#768572}.single-actions>div{display:flex;gap:10px}.single-actions .btn{font-size:12px;padding:11px 20px;border-radius:7px}
.base-dialog{width:min(560px,94vw);max-height:90vh;padding:26px;border:1px solid #d6e0d4;border-radius:14px;color:#264432;overflow:auto}.base-dialog::backdrop{background:rgba(15,40,28,.42)}.base-dialog .section-top h2{font-size:20px}.base-dialog .field input,.base-dialog .field textarea,.registry-layout .field input,.registry-layout .field select,.registry-layout .field textarea{font-size:13px;padding:10px}.base-dialog .field label,.registry-layout .field label{font-size:12px}.base-dialog .field textarea{min-height:70px}.dialog-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:22px}.dialog-actions .btn{font-size:12px}.inline-error{color:#963f32;font-size:12px;line-height:1.6}.registry-layout{display:block}.registry-layout .panel{min-width:0}.registry-layout h2{font-size:18px}.registry-layout .form-section{padding:24px}.registry-tabs{border-bottom:1px solid #dce5d9;margin-bottom:22px;padding-bottom:14px;font-size:13px}.registry-tabs .selected{padding:14px 3px;border-bottom:2px solid #236145;font-weight:600}.table-sub{display:block;font-size:11px;color:#778975;max-width:240px;white-space:normal;margin-top:6px;line-height:1.5}.coords-cell{font-size:11px}.coords-cell a{color:#426c4b;text-decoration:none}.registry-search{margin-bottom:18px}.registry-layout td{vertical-align:middle}.single-main [hidden]{display:none!important}
@media(min-width:1500px){.single-layout{grid-template-columns:minmax(0,1fr) 320px}.single-main .fields{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:1100px){.registry-layout{grid-template-columns:1fr}.single-layout{grid-template-columns:minmax(0,1fr) 245px;gap:16px}.single-main .form-section,.single-aside .form-section{padding:18px}}
@media(max-width:850px){.single-layout{grid-template-columns:1fr}.single-aside{position:static;display:grid;grid-template-columns:1fr 1fr;gap:16px}.single-heading>small{display:none}.registry-layout{grid-template-columns:1fr}}
@media(max-width:550px){.single-aside{display:block}.summary-box{display:none}.single-heading h1{font-size:25px}.single-heading p{font-size:12px}.single-main .fields{grid-template-columns:1fr}.single-main .field input,.single-main .field select,.single-main .field textarea{font-size:16px}.single-actions{flex-direction:column;align-items:stretch;gap:8px;padding:12px 0}.single-actions>span{display:none}.single-actions>div .btn{flex:1;text-align:center;justify-content:center}.base-dialog{padding:20px}.base-dialog .fields{grid-template-columns:1fr}.base-dialog .field input,.base-dialog .field textarea{font-size:16px}.section-top{gap:8px}}

/* Lista de trabalho: página limitada a 25 registros consultados no servidor. */
.list-heading{display:flex;align-items:center;justify-content:space-between;gap:18px;margin:10px 0 24px}.list-heading h1{margin:0;font-size:28px;letter-spacing:-.8px}.list-heading h1>span{display:inline-block;vertical-align:middle;font-size:12px;letter-spacing:0;padding:6px 10px;border-radius:20px;background:#e7eee6;color:#3c6147;margin-left:10px}.list-heading p{margin:7px 0 0;color:#788478;font-size:13px}.list-heading .btn{font-size:12px}.asset-register{padding:20px!important}.list-filters{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap}.list-filters>div{flex:1;min-width:125px}.list-filters>.list-search{flex:2;min-width:230px}.list-filters label{display:block;font-size:10px;font-weight:600;color:#6d7b6c;margin-bottom:7px}.list-filters input,.list-filters select{width:100%;font:12px system-ui;color:#344c39;border:1px solid #d6dfd3;border-radius:7px;padding:10px;min-height:38px;background:#fff}.list-filters .btn{font-size:12px;min-height:38px;padding:9px 16px}.list-filters .text-action{padding-bottom:12px}.list-meta{display:flex;justify-content:space-between;font-size:11px;color:#7b8878;padding:20px 0 13px}.compact-table table{width:100%;min-width:900px;table-layout:auto;border-collapse:collapse}.compact-table th{padding:12px 10px;background:#f5f7f2;color:#75816f;font-size:10px;font-weight:600;white-space:nowrap;text-align:left}.compact-table td{padding:12px 10px!important;border-bottom:1px solid #ebefe7;font-size:12px;vertical-align:middle;color:#41523c;max-width:240px;overflow-wrap:anywhere}.compact-table td small,.list-asset small,.plaque-cell small{display:block;color:#85907e;font-size:10px;line-height:1.5;margin-top:4px}.compact-table tr:hover{background:#f8faf5}.compact-table .highlight-row{background:#ecf5e9}.list-asset{display:flex;align-items:center;gap:9px;min-width:180px}.list-asset>img{width:34px;height:34px;flex:none;object-fit:cover;border-radius:6px}.asset-name{color:#24492f;text-decoration:none;font-weight:600;font-size:12px}.asset-name:hover{text-decoration:underline}.plaque-cell{min-width:110px;font-size:11px!important}.plaque-cell strong{font-size:11px;font-weight:500}.pending-text{color:#879078;font-size:11px}.row-link{border:0;padding:3px 0;background:none;color:#3b6c44;text-decoration:underline;cursor:pointer;font:10px system-ui}.serial-cell{font-variant-numeric:tabular-nums;font-size:11px!important}.row-actions{white-space:nowrap;min-width:80px}.row-actions a{display:inline-block;color:#316542;text-decoration:none;font-size:11px;padding:6px 3px}.row-actions a+a{margin-left:6px}.row-actions a:hover{text-decoration:underline}.compact-table .badge{padding:5px 8px;font-size:10px;white-space:nowrap}.actions-col{text-align:left}.list-empty{text-align:center;padding:45px 12px!important;color:#7e8975!important}.pagination-bar{display:flex;align-items:center;justify-content:space-between;gap:16px;padding-top:18px;font-size:11px;color:#7b8674}.pagination{display:flex;align-items:center;gap:5px;flex-wrap:wrap}.pagination a,.pagination .current-page{display:grid;place-items:center;min-width:30px;height:30px;border-radius:6px;padding:0 9px;text-decoration:none;font-size:11px;border:1px solid #dce4d5;color:#4c6345}.pagination .current-page{background:#214c32;color:#fff;border-color:#214c32}.pagination a:hover{background:#edf3e7}.page-gap{padding:0 5px}.dashboard-actions{display:grid;gap:10px;margin-top:18px}.dashboard-actions a{display:block;padding:15px;background:#f5f7f1;border:1px solid #e4ebdd;border-radius:8px;text-decoration:none;color:#3e5c37}.dashboard-actions strong{font-size:13px}.dashboard-actions small{display:block;color:#819075;font-size:11px;margin-top:5px}
.detail-heading{display:flex;align-items:center;gap:20px;padding:22px 0}.detail-heading h1{font-size:26px;margin:0 0 7px}.detail-heading p{font-size:12px;color:#7b8875;margin:0 0 10px}.detail-photo{width:100px;height:85px;object-fit:contain;border-radius:8px;background:#f0f4eb}.detail-actions{display:flex;align-items:center;gap:10px;margin-left:auto}.detail-actions .btn{font-size:11px;padding:10px 14px}.detail-sections{display:grid;grid-template-columns:1fr 1fr 1fr;gap:18px;align-items:start}.detail-sections .panel{padding:20px}.detail-sections h2,.detail-notes h2{font-size:15px;margin:0 0 18px}.compact-facts{display:grid;gap:14px;margin:0}.compact-facts dt{font-size:10px;color:#859079;margin-bottom:5px}.compact-facts dd{font-size:12px;color:#3c5135;margin:0;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.5}.compact-facts a{color:#386b40}.detail-description{font-size:12px;color:#6e8062;line-height:1.6;white-space:pre-wrap;overflow-wrap:anywhere}.detail-notes{margin-top:18px}.detail-history{margin-top:18px;padding:18px 20px!important}.detail-history summary{cursor:pointer;font-size:13px;font-weight:600;color:#49643f}.detail-history .historico{font-size:12px}.detail-history small{font-size:10px}
@media(max-width:1050px){.detail-sections{grid-template-columns:1fr 1fr}.detail-actions{flex-wrap:wrap}.list-filters>div{min-width:140px}}
@media(max-width:700px){.list-heading{align-items:flex-start}.list-heading h1{font-size:23px}.list-heading h1>span{font-size:10px}.list-heading .btn{white-space:nowrap;font-size:11px}.list-filters>div,.list-filters>.list-search{flex:1 1 45%;min-width:0}.list-filters>.list-search{flex-basis:100%}.list-filters input,.list-filters select{font-size:16px}.pagination-bar{flex-direction:column;align-items:flex-start}.asset-register{padding:14px!important}.detail-sections{grid-template-columns:1fr}.detail-heading{flex-wrap:wrap}.detail-actions{width:100%;margin-left:0}.detail-heading h1{font-size:23px}.compact-table th,.compact-table td{display:table-cell!important}.detail-photo{width:70px;height:65px}}

/* Correções de alinhamento: perfil, saída no menu e coluna exclusiva de fotos. */
.top{justify-content:flex-start;gap:20px}.top .crumb{flex:1;min-width:0}.top .profile{margin-left:auto;flex:none;justify-content:flex-end;min-width:0;text-align:left;font-size:13px}.top .profile>div{max-width:240px;overflow-wrap:anywhere}.top .avatar{flex:none}.top .profile small{font-size:11px;margin-top:3px}
.sidebar-logout{margin:6px 0 0;padding-top:6px;border-top:1px solid #ffffff15}.logout-button{width:100%;display:flex;align-items:center;gap:13px;border:0;background:none;color:#d5e2d8;font:400 13px system-ui;text-align:left;cursor:pointer;padding:12px;border-radius:6px;min-height:42px}.logout-button:hover{background:#ffffff10;color:white}.logout-button:focus-visible{outline:2px solid #accdb0;outline-offset:2px}.logout-button svg{width:18px;height:18px;flex:none}.sidebar .sideart{display:none}
.compact-table table{table-layout:fixed;min-width:1120px}.col-photo{width:64px}.col-plaque{width:145px}.col-name{width:230px}.col-serial{width:160px}.col-local{width:210px}.col-person{width:145px}.col-status{width:110px}.col-actions{width:100px}.compact-table td{font-size:13px;padding:12px 10px!important;line-height:1.45}.compact-table th{font-size:11px;padding:13px 10px}.compact-table td small{font-size:11px}.compact-table .photo-cell{padding:10px!important;text-align:center}.photo-header{text-align:center!important}.row-photo{display:flex;width:42px;height:42px;align-items:center;justify-content:center;background:#f3f6f0;border:1px solid #e2e9dc;border-radius:7px;overflow:hidden;margin:auto;color:#a1ae98;text-decoration:none}.row-photo img{display:block;width:100%;height:100%;object-fit:contain;padding:3px;background:white}.row-photo svg{width:22px;height:22px}.list-asset{display:block;min-width:0}.list-asset>div{min-width:0}.asset-name{font-size:13px;display:block;line-height:1.45;overflow-wrap:anywhere}.plaque-cell strong,.plaque-cell{font-size:12px!important}.serial-cell{font-size:12px!important}.row-actions a{font-size:12px;padding:7px 0}.compact-table .badge{font-size:11px}.row-link{font-size:11px}.list-filters label{font-size:11px}.list-filters input,.list-filters select{font-size:13px}.list-meta,.pagination-bar{font-size:12px}
.detail-photo-slot{width:112px;height:96px;display:grid;place-items:center;flex:none;border:1px solid #e0e7dc;border-radius:9px;background:#f2f6ed;color:#8d9d80;overflow:hidden;font-size:11px}.detail-photo-slot .detail-photo{width:100%;height:100%;object-fit:contain;padding:6px;background:white;border-radius:0}.dashboard-top-actions{display:flex;gap:10px;align-items:center}.dashboard-top-actions .btn{font-size:12px}.reader-layout{display:grid;grid-template-columns:1fr 1fr;gap:24px}.reader-layout .panel{min-width:0}.reader-layout h2{font-size:18px}.reader-buttons{display:flex;gap:12px;margin-top:20px}#qr-video{width:100%;max-height:380px;object-fit:cover;background:#132d20;border-radius:10px;margin-top:18px}#qr-video[hidden],#qr-stop[hidden]{display:none}
@media(max-width:700px){.top{gap:10px}.top .profile{display:flex;font-size:12px}.top .profile>div{max-width:150px}.top .profile small{display:block;font-size:10px}.top .crumb{display:none}.top .avatar{width:30px;height:30px}.compact-table table{min-width:1120px}.list-filters input,.list-filters select{font-size:16px}.dashboard-top-actions{flex-wrap:wrap}.list-heading:has(.dashboard-top-actions){flex-wrap:wrap}.reader-layout{grid-template-columns:1fr}.detail-photo-slot{width:80px;height:72px}}

.nav-group{margin:0}.nav-group summary{list-style:none;display:flex;align-items:center;gap:13px;cursor:pointer;padding:12px;border-radius:6px;font-size:13px;color:#d8e5db}.nav-group summary::-webkit-details-marker{display:none}.nav-group summary:hover,.nav-group summary.active{background:#ffffff16}.nav-group summary>span{flex:1}.nav-group .nav-chevron{width:16px;height:16px;transition:transform .15s}.nav-group[open] .nav-chevron{transform:rotate(180deg)}.nav-submenu{padding:5px 0 8px 30px;border-left:1px solid #ffffff1f;margin-left:20px}.nav .nav-submenu a{font-size:12px;padding:10px 12px;color:#b6cbbb}.nav .nav-submenu a.selected{color:#fff;background:#ffffff12}.nav-group summary:focus-visible{outline:2px solid #94bba0;outline-offset:2px}.guide-hub{text-align:center;padding:20px 15px 28px;border-bottom:1px solid #e3eadc}.guide-hub>span{font-size:9px;letter-spacing:1.5px;color:#829273}.guide-hub h2{font-size:26px;margin:12px 0 8px}.guide-hub p{font-size:12px;color:#75866c}.guide-map{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:13px;padding:25px 0}.guide-node{display:flex;flex-direction:column;align-items:flex-start;text-align:left;border:1px solid #dce6d4;background:#f8faf4;border-radius:10px;padding:17px;cursor:pointer;color:#426638;gap:8px;min-height:116px}.guide-node small{font-size:10px;color:#8d9c7e}.guide-node strong{font-size:13px}.guide-node span{font-size:11px;color:#819375}.guide-node[aria-pressed=true]{background:#edf5e5;border-color:#588649;box-shadow:0 0 0 1px #588649}.guide-node:focus-visible{outline:2px solid #588649;outline-offset:3px}.guide-explanation{padding:24px;border:1px solid #dce7d3;border-radius:10px;background:#fff}.guide-explanation h2{font-size:20px;margin:0 0 14px}.guide-explanation p{font-size:14px;line-height:1.8;color:#5e7353}.guide-explanation .guide-example{font-size:12px;background:#f4f8ed;padding:15px;border-radius:7px}.guide-explanation a{font-size:12px;color:#1d4ed8;text-decoration:underline;text-underline-offset:3px;overflow-wrap:anywhere}.guide-explanation a:visited{color:#1d4ed8}.guide-explanation a:hover{color:#1e40af;text-decoration-thickness:2px}.guide-explanation a:focus-visible{outline:2px solid #1d4ed8;outline-offset:4px;border-radius:2px}.registry-layout .fields{gap:16px}.registry-layout .field textarea{min-height:76px}.registry-layout .form-section>p{font-size:12px}.registry-layout .tablewrap table{min-width:420px}@media(max-width:1000px){.guide-map{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:550px){.guide-map{gap:9px}.guide-node{padding:13px;min-height:110px}.guide-node strong{font-size:12px}.guide-explanation{padding:18px}.registry-layout input,.registry-layout select{font-size:16px!important}}


/* Cadastros: consulta e formulário são páginas distintas. */
.registry-navigation{display:flex;flex-wrap:wrap;gap:8px;padding:0 0 18px;margin:0 0 24px;border-bottom:1px solid #dce5dd}
.registry-navigation a{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:11px 20px;border:1px solid #d8e2da;border-radius:8px;background:#fff;color:#4d6658;text-decoration:none;font-size:13px;font-weight:600;line-height:1.4}
.registry-navigation a.current{background:#174c37;color:#fff;border-color:#174c37;box-shadow:0 2px 4px #153b2410}
.registry-navigation a:hover{border-color:#39775b}.registry-navigation a:focus-visible{outline:3px solid #80ad97;outline-offset:3px}
.registry-workspace{min-width:0}.registry-list{width:100%;min-width:0}.registry-list h2,.registry-form h2{font-size:19px;margin:0 0 8px}
.registry-list .panelhead p{font-size:12px;color:#76877b;margin:0}.registry-list .tablewrap table{min-width:640px;width:100%}.registry-list td{vertical-align:middle}
.registry-toolbar{display:flex;align-items:flex-end;gap:12px;padding:20px 0;margin-bottom:4px}.registry-toolbar .field:first-child{flex:1;min-width:180px}.registry-toolbar .field:nth-child(2){width:180px}.registry-toolbar label{font-size:12px}.registry-toolbar input,.registry-toolbar select{font-size:13px;min-height:42px;padding:10px 12px}.registry-toolbar .btn{min-height:42px;white-space:nowrap}
.registry-form{width:100%;max-width:960px;margin:0 auto 24px;padding:30px;border-radius:12px}.registry-form>p{font-size:13px;color:#728276;line-height:1.6;margin:0 0 24px}.registry-form .fields{gap:22px 24px;margin-top:24px}.registry-form .field label{font-size:12px;margin-bottom:8px}.registry-form .field input,.registry-form .field select,.registry-form .field textarea{font-size:14px;padding:12px;min-height:44px;border-radius:8px}.registry-form .field textarea{min-height:100px;resize:vertical}.registry-form .field small{font-size:11px;line-height:1.6}.registry-form .dialog-actions{border-top:1px solid #e3e9e4;padding-top:22px;margin-top:26px}.registry-form .dialog-actions .btn{min-height:44px;min-width:120px;font-size:13px}.registry-form .hint{display:block;line-height:1.7;margin-top:16px}
.registry-list .coords-cell a{color:#1d4ed8;text-decoration:underline;text-underline-offset:3px}.registry-list .empty{padding:32px;text-align:center;color:#76877b}
@media(max-width:700px){.registry-toolbar{flex-wrap:wrap}.registry-toolbar .field:first-child{flex-basis:100%;min-width:0}.registry-toolbar .field:nth-child(2){flex:1;width:auto}.registry-form{padding:22px}.registry-form .fields{grid-template-columns:1fr}.registry-form .field input,.registry-form .field select,.registry-form .field textarea,.registry-toolbar input,.registry-toolbar select{font-size:16px}.registry-navigation a{flex:1;padding:10px 12px;text-align:center}.registry-form .dialog-actions .btn{flex:1;min-width:0}}


/* Operações patrimoniais: tabelas compactas e formulários em página própria. */
.op-section{margin-top:24px;margin-bottom:24px}.op-section h2,.op-picker h2,.op-document h2{font-size:19px}.op-actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:18px 0}.op-detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:22px}.op-detail-grid h2{font-size:18px}.op-selected{padding:18px;border:1px solid #c6dbcc;background:#f0f6f1;border-radius:9px;display:flex;flex-direction:column;gap:8px}.op-selected span,.op-selected small{font-size:12px;color:#54715f}.op-picker{max-width:960px;margin:0 auto 22px}.op-check{display:flex;gap:12px;align-items:flex-start;font-size:13px;line-height:1.7;margin:22px 0}.op-check input{width:18px;height:18px;flex-shrink:0;margin-top:3px;accent-color:#174c37}.op-document{max-width:900px;margin:auto;padding:40px}.op-document-head{text-align:center;border-bottom:2px solid #174c37;padding-bottom:24px;margin-bottom:24px}.op-document-head>strong{font-size:26px;display:block}.op-document-head>span{font-size:10px;letter-spacing:2px;display:block;margin-top:7px}.op-document-head p{font-weight:600;font-size:20px;margin:24px 0 10px}.op-document-head small{font-size:12px;color:#6e8074}.op-document h3{font-size:14px;margin:24px 0 8px}.op-signatures{display:grid;grid-template-columns:1fr 1fr;gap:30px;margin-top:65px;text-align:center}.op-signatures div{display:flex;flex-direction:column;gap:10px;font-size:12px;overflow-wrap:anywhere}.op-signatures small{font-size:10px;color:#78877d}.op-hash{overflow-wrap:anywhere;font-size:9px;color:#718277;line-height:1.7;margin-top:40px}.op-aceite-assinatura span{display:inline-block;align-self:center;font-size:10px;letter-spacing:1px;text-transform:uppercase;color:#15573f;border:1.5px solid #15573f;border-radius:6px;padding:7px 12px;font-weight:700}.op-aceite-status{padding:16px 18px;border-radius:10px;background:#fff7e6;border:1px solid #f0dcae;margin-bottom:18px}.op-aceite-status.ok{background:#e9f4ec;border-color:#c5dfcd}.op-aceite-status strong{font-size:14px}.op-aceite-status p{font-size:13px;line-height:1.6;margin:6px 0 10px;color:#4f6658}.op-aceite-status form{margin:0}.op-aceite-form{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) auto;gap:14px;align-items:end;margin-top:12px}.op-aceite-historico{margin-top:18px}.op-aceite-historico summary{cursor:pointer;font-size:13px;font-weight:600;color:#49643f}.op-aceite-historico li>span:first-child{display:flex;flex-direction:column;gap:5px;min-width:0;overflow-wrap:anywhere}.op-aceite-historico .badge{align-self:center;white-space:nowrap}@media(max-width:700px){.op-aceite-form{grid-template-columns:1fr}}.op-attachments{padding:0;list-style:none}.op-attachments li{padding:12px 0;border-bottom:1px solid #e7ece8;display:flex;justify-content:space-between;gap:12px;font-size:13px}.op-attachments a{color:#1d4ed8;text-decoration:underline}.op-attachments small{color:#7b897e}.op-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px}.op-metrics article{background:#fff;border:1px solid #e0e8e2;border-radius:10px;padding:20px;display:flex;flex-direction:column;gap:10px}.op-metrics span{font-size:12px;color:#708276}.op-metrics strong{font-size:26px}.op-report-filters{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px;align-items:end;margin-bottom:20px}.op-report-filters label{font-size:12px}.op-report-filters select,.op-report-filters input{font-size:13px;min-height:42px}.op-report-filters .op-actions{margin:0}.list-filters{display:grid;grid-template-columns:minmax(170px,1.6fr) repeat(5,minmax(100px,1fr)) auto}.list-filters>div,.list-filters>.list-search{min-width:0}.list-filters input,.list-filters select{width:100%}
@media(max-width:1100px){.list-filters{grid-template-columns:repeat(3,minmax(0,1fr))}.op-report-filters{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:700px){.op-detail-grid{grid-template-columns:1fr}.op-metrics{grid-template-columns:1fr 1fr;gap:10px}.op-metrics article{padding:16px}.op-report-filters{grid-template-columns:1fr}.op-document{padding:22px}.op-signatures{grid-template-columns:1fr;gap:55px}.op-report-filters input,.op-report-filters select{font-size:16px}.list-filters{grid-template-columns:1fr}.op-actions .btn{flex:1;justify-content:center}.op-picker{padding:20px}}
@media print{@page{size:A4;margin:16mm}.sidebar,.top,footer,.menu-overlay,.mobile,.feedback,.op-no-print,.op-document~section{display:none!important}body,.shell,main{background:#fff!important;display:block!important;margin:0!important;padding:0!important;width:100%!important;max-width:none!important}.op-document{border:none!important;box-shadow:none!important;padding:0!important;margin:0!important;max-width:none!important}.op-signatures{display:grid;grid-template-columns:1fr 1fr;break-inside:avoid}.op-document h2,.op-document h3{break-after:avoid}.op-document p,.op-document dd{color:#111}.op-document-head{border-color:#222}.op-hash{color:#444}}


/* Seleção integrada: o formulário completo aparece desde a abertura. */
.op-picker-v2,.op-entry-form{width:100%;max-width:none;margin:0 0 22px;padding:26px 30px}.picker-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:22px}.picker-heading h2{font-size:19px;margin:0 0 7px}.picker-heading p{font-size:12px;color:#6d8174;margin:0;line-height:1.6}.picker-state{font-size:11px;color:#476352;background:#edf3ee;padding:8px 12px;border-radius:20px;white-space:nowrap}.picker-input-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px}.picker-search{position:relative;width:100%}.picker-search .field{width:100%;min-width:0}.picker-search label{font-size:12px}.picker-search input{width:100%;min-height:46px;font-size:14px;padding:12px 14px}.picker-search .btn{min-height:46px}.picker-search .field>small{font-size:11px;color:#77887b;display:block;margin-top:8px}.picker-search #picker-feedback{font-size:12px;color:#637b6b;line-height:1.5;min-height:18px;margin:10px 0 0}.picker-results{position:absolute;top:80px;left:0;right:0;z-index:20;max-height:340px;overflow:auto;background:white;border:1px solid #bacfbe;border-radius:9px;box-shadow:0 12px 28px #1d402323}.picker-results[hidden]{display:none}.picker-result{width:100%;display:flex;flex-direction:column;gap:6px;text-align:left;padding:14px 16px;border:0;border-bottom:1px solid #e5ece6;background:#fff;color:#244434;cursor:pointer}.picker-result:hover,.picker-result:focus-visible{background:#edf5ef;outline:2px solid #548266;outline-offset:-2px}.picker-result strong{font-size:13px}.picker-result span{font-size:12px}.picker-result small{font-size:11px;color:#6d8274}.picker-no-results{padding:20px;font-size:13px}.picker-selected-header{display:flex;justify-content:space-between;align-items:center;gap:16px;border-top:1px solid #e4ebe5;margin-top:18px;padding-top:20px}.picker-eyebrow{font-size:9px;letter-spacing:1.3px;color:#74887a}.picker-selected-header h3{font-size:17px;margin:8px 0}.picker-selected-header p{font-size:12px;color:#708377;margin:0}.picker-origin{display:grid;grid-template-columns:1fr 1fr;gap:22px;background:#f4f7f4;border:1px solid #e3eae3;border-radius:8px;padding:16px 18px;margin-top:18px}.picker-origin>div{display:flex;flex-direction:column;gap:7px;min-width:0}.picker-origin span{font-size:11px;color:#748478}.picker-origin strong{font-size:13px;font-weight:600;overflow-wrap:anywhere}.picker-origin small{font-size:11px;color:#76877a;overflow-wrap:anywhere}.op-data-fields{border:0;padding:0;margin:0;min-width:0}.op-data-fields:disabled{opacity:.72}.op-selection-hint{padding:12px 16px;background:#f2f5f1;border-left:3px solid #90ac98;border-radius:5px;font-size:12px!important;color:#536e5e!important;line-height:1.6}.op-picker-v2 [hidden],.op-entry-form [hidden]{display:none!important}.op-entry-form .fields{margin-top:18px}.op-entry-form>h2{margin-bottom:10px}.op-entry-form .dialog-actions{margin-top:22px}.op-entry-form .field textarea{min-height:90px}.op-entry-form .field small{display:block;margin-top:7px;line-height:1.5}
@media(max-width:700px){.op-picker-v2,.op-entry-form{padding:20px}.picker-heading{flex-direction:column;gap:12px}.picker-input-row{grid-template-columns:minmax(0,1fr) auto}.picker-search input{font-size:16px}.picker-origin{grid-template-columns:1fr;gap:18px}.picker-selected-header{align-items:flex-start}.picker-selected-header h3{font-size:16px}.picker-search .btn{font-size:11px;padding:10px}.picker-results{top:80px}}

/* Identidade institucional, ficha do bem e conferência móvel. */
textarea{font:inherit}.content-link,.content-link:visited{color:#1d4ed8;text-decoration:underline;text-underline-offset:3px}.content-link:hover{color:#1e40af}.overview-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px;margin-bottom:24px}.overview-metrics>a{display:flex;flex-direction:column;gap:12px;border:1px solid #dfe7e0;border-radius:11px;background:white;padding:23px;color:#234333}.overview-metrics>a:hover{border-color:#7da18a}.overview-metrics span{font-size:12px;color:#667b6e}.overview-metrics strong{font-size:32px;line-height:1.15;letter-spacing:-1px}.overview-metrics small{font-size:11px;color:#7b897f;line-height:1.5}.metric-danger{color:#ba3f32}.overview-columns{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr);gap:24px}.overview-columns h2{font-size:19px}.overview-columns .panelhead p,.op-section .panelhead p{font-size:11px;color:#7c8b80;line-height:1.5}.overview-bar{margin-top:24px}.overview-bar>div:first-child{display:flex;justify-content:space-between;gap:15px;margin-bottom:10px;font-size:12px}.overview-bar strong{font-weight:600;white-space:nowrap}.overview-bar .track{height:9px}.attention-item{display:flex;flex-direction:column;gap:8px;margin-top:14px;padding:16px;border-radius:9px;background:#f3f6f3;border:1px solid transparent}.attention-item:hover{border-color:#b5cbbd}.attention-item strong{font-size:12px;font-weight:600}.attention-item span{font-size:11px;color:#64796b;line-height:1.6}.attention-item small{font-size:11px;text-decoration:underline;color:#2a674b;text-underline-offset:3px}.attention-warn{background:#fcf2e7}.attention-danger{background:#fceeee}.attention-ok{background:#eaf3ed}.asset-profile-head{display:flex;gap:23px;align-items:center;margin-top:18px}.asset-profile-photo{width:112px;height:112px;border-radius:12px;border:1px solid #d6e2d9;background:#eaf0e9;display:flex;align-items:center;justify-content:center;flex-shrink:0;overflow:hidden}.asset-profile-photo img{width:100%;height:100%;object-fit:contain;padding:7px}.asset-profile-photo span{font-size:12px;color:#819284}.asset-profile-title{min-width:0}.asset-profile-title>small{font-size:12px;color:#327253;font-family:monospace;font-weight:600}.asset-profile-title h1{font-size:28px;line-height:1.3;letter-spacing:-.6px;margin:10px 0 14px;overflow-wrap:anywhere}.asset-badges{display:flex;gap:8px;flex-wrap:wrap}.asset-profile-actions{display:flex;flex-wrap:wrap;gap:10px;margin:24px 0}.asset-profile-actions .btn{font-size:12px}.asset-profile-layout{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:24px}.asset-profile-main,.asset-profile-aside{min-width:0;display:flex;flex-direction:column;gap:22px}.asset-profile-layout h2{font-size:18px;margin:0 0 18px}.asset-profile-layout .compact-facts{grid-template-columns:repeat(3,minmax(0,1fr));gap:22px}.asset-profile-layout .compact-facts dd{font-size:13px;line-height:1.6;overflow-wrap:anywhere}.asset-profile-layout .compact-facts dt{font-size:10px}.tag-preview{display:flex;align-items:center;padding:12px 8px;gap:8px;background:white;border:1px solid #52645a;border-radius:8px;color:#172c20}.tag-preview>img{width:105px;height:105px;flex-shrink:0;image-rendering:pixelated}.tag-preview>div{display:flex;flex-direction:column;gap:10px;min-width:0}.tag-preview small{font-size:8px;letter-spacing:.6px}.tag-preview strong{font:700 13px/1.5 monospace;overflow-wrap:anywhere}.tag-preview span{font-size:9px;color:#6f8074}.asset-documents{padding:0;list-style:none;margin:0 0 14px}.asset-documents li{font-size:12px;line-height:1.6;padding:10px 0;border-bottom:1px solid #e7ece7}.asset-documents small{display:block;font-size:10px;color:#8a968e;margin-top:6px}.asset-timeline article{display:flex;gap:14px;padding:0 0 23px}.asset-timeline article>span{height:10px;width:10px;background:#297652;border-radius:50%;margin-top:4px;flex-shrink:0;position:relative}.asset-timeline article:not(:last-child)>span:after{content:'';position:absolute;top:14px;left:4px;width:2px;height:35px;background:#dce7de}.asset-timeline article>div{min-width:0}.asset-timeline strong{font-size:12px}.asset-timeline p{font-size:11px;color:#7e8e83;margin:8px 0}.asset-timeline summary{font-size:10px;color:#3d7956;cursor:pointer}.history-changes{margin:12px 0;font-size:11px}.history-changes>div{padding:8px 0}.history-changes dt{font-weight:600;color:#536b5b}.history-changes dd{margin:5px 0;color:#728477;overflow-wrap:anywhere}.inventory-hero{border-radius:12px;background:#123f30;padding:26px 30px;margin:0 0 22px;color:#fff}.inventory-hero>small{font-size:10px;color:#a9c9b5;letter-spacing:1.5px}.inventory-hero h2{font-size:25px;margin:12px 0 24px}.inventory-progress-title{display:flex;align-items:baseline;justify-content:space-between;gap:15px}.inventory-progress-title strong{font-size:32px}.inventory-progress-title strong span{font-size:18px;color:#afcbb8}.inventory-progress-title>span{font-size:14px;color:#c6dccd}.inventory-hero progress{display:block;height:10px;width:100%;margin-top:18px;border:0;border-radius:20px;overflow:hidden;accent-color:#72c796;background:#235841}.inventory-hero progress::-webkit-progress-bar{background:#235841}.inventory-hero progress::-webkit-progress-value{background:#72c796}.inventory-action-panel{margin:0 0 24px}.inventory-read{width:100%;min-height:125px;border:0;border-radius:12px;background:#20684d;color:white;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:11px;padding:20px}.inventory-read>svg{width:32px;height:32px}.inventory-read strong{font-size:20px}.inventory-read span{font-size:11px;color:#c5dfce}.inventory-action-panel>div{display:flex;gap:12px;margin-top:12px}.inventory-action-panel>div>.btn{flex:1;justify-content:center}.inventory-manual{margin-top:20px}.inventory-manual>label{display:block;font-size:12px;margin-bottom:9px}.inventory-manual>div{display:flex;gap:10px}.inventory-manual input{min-width:0;flex:1;border:1px solid #cbd9cf;border-radius:8px;padding:12px;font-size:14px}.inventory-mobile-cards{display:none}.inventory-camera-dialog{width:min(560px,94vw);border:1px solid #c4d8c9;border-radius:12px;color:#244534;padding:24px}.inventory-camera-dialog::backdrop{background:#103021a6}.inventory-camera-dialog h2{font-size:19px}.inventory-camera-dialog video{width:100%;min-height:150px;background:#14251c;margin-top:18px;border-radius:8px}.inventory-camera-dialog p{font-size:13px;line-height:1.7}
@media(max-width:1200px){.asset-profile-layout{grid-template-columns:minmax(0,1fr) 300px}.asset-profile-layout .compact-facts{grid-template-columns:repeat(2,minmax(0,1fr))}.overview-metrics{gap:12px}.overview-metrics>a{padding:18px}}
@media(max-width:1000px){.overview-columns{grid-template-columns:1fr}.overview-metrics{grid-template-columns:1fr 1fr}.asset-profile-layout{grid-template-columns:1fr}.asset-profile-aside{display:grid;grid-template-columns:1fr 1fr;align-items:start}.asset-profile-aside>section:last-child{grid-column:1/-1}}
@media(max-width:700px){.overview-metrics>a{padding:17px 14px}.overview-metrics strong{font-size:28px}.overview-metrics span{font-size:11px}.overview-metrics small{font-size:10px}.asset-profile-head{gap:14px;align-items:flex-start}.asset-profile-photo{width:78px;height:78px}.asset-profile-title h1{font-size:21px;margin:7px 0 11px}.asset-profile-actions .btn{flex:1;justify-content:center}.asset-profile-layout .compact-facts{grid-template-columns:1fr 1fr;gap:18px}.asset-profile-aside{display:flex}.inventory-desktop-table,.inventory-desktop-metrics{display:none}.inventory-mobile-cards{display:block}.inventory-mobile-cards article{border:1px solid #dce5de;border-radius:10px;padding:17px;margin-top:12px;display:flex;align-items:flex-start;flex-wrap:wrap;gap:13px}.inventory-mobile-cards article>div{flex:1;min-width:160px;display:flex;flex-direction:column;gap:8px}.inventory-mobile-cards article strong{font-size:15px}.inventory-mobile-cards article small{font:12px monospace;color:#627d6b}.inventory-mobile-cards article span:not(.badge){font-size:11px;color:#839488}.inventory-mobile-cards article>.btn{width:100%;justify-content:center;font-size:12px}.inventory-hero{padding:22px}.inventory-hero h2{font-size:23px}.inventory-progress-title strong{font-size:30px}.inventory-read{min-height:155px}.inventory-read strong{font-size:23px}.inventory-manual input{font-size:16px}.inventory-manual>div{flex-wrap:wrap}.inventory-manual .btn{justify-content:center}.inventory-action-panel>div>.btn{font-size:12px;padding:12px}.inventory-camera-dialog{padding:18px}.asset-timeline article{padding-bottom:23px}}

/* Dashboard: gráficos nativos, sem dependência de serviços externos. */
.analytics-filters{margin-bottom:24px}.analytics-filter-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px}.analytics-filters .field label{font-size:12px}.analytics-filters input,.analytics-filters select{width:100%;min-height:42px;padding:10px 12px;font-size:13px}.analytics-filter-bottom{display:flex;align-items:flex-end;gap:12px;margin-top:18px}.analytics-filter-bottom>.field{flex:1}.analytics-filter-bottom .btn{min-height:42px;white-space:nowrap}.analytics-filters>.hint{margin:18px 0 0;line-height:1.7}.analytics-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px;margin-bottom:24px}.analytics-kpi{display:flex;flex-direction:column;gap:13px;padding:24px;background:#fff;border:1px solid #dce5de;border-radius:12px}.analytics-kpi:hover{border-color:#6f9b81;box-shadow:0 4px 14px #1a4a2e0a}.analytics-kpi>span:first-child{font-size:12px;color:#6b8072}.analytics-kpi>strong{font-size:30px;line-height:1.2;letter-spacing:-.8px;color:#204d36;overflow-wrap:anywhere}.analytics-kpi>small{font-size:11px;color:#849288;line-height:1.6}.analytics-kpi-action{font-size:11px;color:#327453;margin-top:auto}.analytics-charts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}.analytics-chart{min-width:0}.analytics-chart-title{display:flex;align-items:center;justify-content:space-between;gap:15px}.analytics-chart-title h2{font-size:19px;margin:0}.analytics-chart-title>span{font-size:10px;color:#7b8f80;background:#f1f5f1;padding:7px 10px;border-radius:14px;white-space:nowrap}.analytics-chart-note{font-size:11px;color:#839487;line-height:1.7;margin:13px 0 24px}.analytics-bars{display:flex;flex-direction:column;gap:20px}.analytics-bar{display:block;padding:4px 0;border-radius:5px}.analytics-bar:hover{background:#f5f8f3}.analytics-bar>div:first-child{display:flex;justify-content:space-between;align-items:baseline;gap:18px;font-size:12px;margin-bottom:9px}.analytics-bar>div:first-child>span{overflow-wrap:anywhere;min-width:0}.analytics-bar strong{font-size:12px;white-space:nowrap}.analytics-track{height:12px;background:#edf2ec;border-radius:7px;overflow:hidden}.analytics-track>span{display:block;height:100%;background:#397c58;border-radius:7px}.analytics-bar>small{display:block;margin-top:7px;font-size:10px;color:#8b9a8e}.analytics-bar:focus-visible,.analytics-kpi:focus-visible,.analytics-legend a:focus-visible{outline:2px solid #397c58;outline-offset:5px}.analytics-donut-layout{display:flex;align-items:center;justify-content:center;gap:25px;min-height:230px}.analytics-donut{width:210px;height:210px;flex-shrink:0;fill:none;stroke:none}.analytics-donut circle{stroke-linecap:butt;stroke-linejoin:miter}.analytics-donut a:hover circle{opacity:.8}.analytics-donut text{fill:#2b533b;stroke:none}.donut-total{font-size:17px;font-weight:700}.donut-caption{font-size:7px;fill:#819486!important}.analytics-legend{flex:1;min-width:0;display:flex;flex-direction:column;gap:15px}.analytics-legend>a{display:flex;align-items:center;gap:9px;font-size:11px;line-height:1.5}.analytics-legend>a>span:nth-child(2){flex:1}.analytics-legend strong{font-size:12px}.analytics-legend small{font-size:10px;color:#87988c}.legend-dot{width:9px;height:9px;flex-shrink:0;border-radius:50%}.analytics-wide{grid-column:1/-1}.analytics-situations{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:26px;margin-top:26px}.analytics-footer-links{display:flex;justify-content:space-between;flex-wrap:wrap;gap:18px;margin-top:24px;font-size:12px}.analytics-empty{text-align:center;padding:32px;margin-bottom:24px}.analytics-empty h2{font-size:19px}.analytics-empty p,.analytics-no-data{font-size:12px;color:#8a9b8c;line-height:1.7}.col-category{width:130px}
@media(max-width:1200px){.analytics-filter-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.analytics-kpis{gap:12px}.analytics-kpi{padding:19px}.analytics-kpi>strong{font-size:25px}.analytics-donut-layout{flex-direction:column}.analytics-legend{width:100%}}
@media(max-width:850px){.analytics-charts{grid-template-columns:1fr}.analytics-wide{grid-column:auto}.analytics-kpis{grid-template-columns:1fr 1fr}.analytics-situations{grid-template-columns:1fr 1fr}.analytics-filter-grid{grid-template-columns:1fr 1fr}.analytics-donut-layout{flex-direction:row}.analytics-chart-title{flex-wrap:wrap}}
@media(max-width:550px){.analytics-filter-grid{grid-template-columns:1fr}.analytics-filter-bottom{flex-wrap:wrap}.analytics-filter-bottom>.field{flex-basis:100%}.analytics-filter-bottom .btn{flex:1;justify-content:center}.analytics-filters input,.analytics-filters select{font-size:16px}.analytics-kpi{padding:17px 14px}.analytics-kpi>strong{font-size:23px}.analytics-kpi>span:first-child{font-size:11px}.analytics-kpi>small{font-size:10px}.analytics-charts{gap:18px}.analytics-donut-layout{flex-direction:column}.analytics-donut{width:190px;height:190px}.analytics-situations{grid-template-columns:1fr}.analytics-chart-title h2{font-size:18px}}

/* Painel de campanha: progresso, ocorrências e equipe. */
.inventory-heading{align-items:flex-end}.inventory-overline{font-size:9px;letter-spacing:1.3px;color:#8b9a8d;display:block;margin-bottom:7px}.inventory-heading-actions{display:flex;gap:10px;flex-wrap:wrap}.inventory-heading-actions>.btn{font-size:12px}.campaign-summary{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:28px;padding:25px 28px;border-radius:12px;background:#143f30;color:white;align-items:center}.campaign-summary-tags{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin-bottom:13px}.campaign-summary-tags>span{font-size:10px;background:#ffffff14;padding:5px 9px;border-radius:20px;color:#bcd8c6}.campaign-summary-tags .campaign-state{background:#365e3c;color:#d7e7a2;display:inline-flex;align-items:center;gap:6px}.campaign-state>i{width:6px;height:6px;border-radius:50%;background:#c4de74}.campaign-summary-tags .campaign-finished{background:#335449;color:#d5e2d9}.campaign-finished>i{background:#a4c2b1}.campaign-summary h2{font-size:24px;letter-spacing:-.5px;margin:0 0 9px}.campaign-summary p{font-size:12px;line-height:1.7;margin:0 0 6px;color:#c6d9cc}.campaign-summary-info>small{font-size:10px;line-height:1.7;color:#a8c6b3;display:block;overflow-wrap:anywhere}.campaign-summary-metrics{display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:22px;align-items:start}.campaign-summary-metrics>div{display:flex;flex-direction:column;gap:10px;min-width:0}.campaign-summary-metrics strong{font-size:32px;line-height:1.2;white-space:nowrap;letter-spacing:-1px}.campaign-summary-metrics strong>span{font-size:14px;letter-spacing:0;color:#a7c8b4}.campaign-summary-metrics small{font-size:10px;line-height:1.6;color:#acc8b6}.campaign-primary-action{display:flex;align-items:center;justify-content:space-between;gap:18px;margin:18px 0 24px}.campaign-primary-action p{font-size:12px;color:#7b8e80}.campaign-primary-action .btn{font-size:12px}.campaign-grid{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);gap:24px;align-items:start}.campaign-panel-title{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:18px;flex-wrap:wrap}.campaign-panel-title h2{font-size:17px;margin:0}.campaign-note{font-size:11px;color:#7e9183;line-height:1.7;margin:12px 0 20px}.campaign-progress-legend{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.campaign-progress-legend>span{display:inline-flex;align-items:center;gap:5px;font-size:9px;color:#829086}.campaign-progress-legend i{width:7px;height:7px;border-radius:2px;display:inline-block}.seg-conferido{background:#286e50}.seg-divergencia{background:#e5a03c}.seg-nao-localizado{background:#cd4b44}.seg-pendente{background:#e8eee7}.campaign-location{display:block;margin-top:23px;border-radius:4px}.campaign-location:first-of-type{margin-top:14px}.campaign-location:hover{background:#f7f9f5}.campaign-location>div:first-child{display:flex;align-items:baseline;justify-content:space-between;gap:16px;margin-bottom:10px}.campaign-location strong{font-size:12px;font-weight:600;overflow-wrap:anywhere}.campaign-location>div>span{font-size:11px;color:#819184;white-space:nowrap}.campaign-segments{height:10px;display:flex;border-radius:7px;overflow:hidden;background:#e8eee7}.campaign-segments>span{display:block;height:100%;flex-shrink:0}.campaign-issue-counter{font-size:10px;white-space:nowrap;color:#b1783c;background:#fcf1e6;border-radius:20px;padding:6px 9px}.campaign-issue{display:flex;gap:12px;padding:14px 0;border-bottom:1px solid #edf0eb;align-items:flex-start}.campaign-issue>div{flex:1;min-width:0}.campaign-issue strong{display:block;font-size:12px;font-weight:600;line-height:1.5}.campaign-issue small{display:block;font-size:10px;color:#829385;line-height:1.6;margin-top:5px;overflow-wrap:anywhere}.campaign-issue p{font-size:10px;color:#87958a;line-height:1.6;margin:7px 0 0}.campaign-issue-tag{font-size:9px;padding:5px 7px;white-space:nowrap;border-radius:5px}.issue-danger{color:#bf4944;background:#fdecea}.issue-warning{color:#b47b33;background:#fdf1e2}.campaign-issue-link{display:inline-block;margin-top:18px;font-size:11px}.campaign-no-issues{padding:20px 0}.campaign-no-issues strong{font-size:13px;color:#547963}.campaign-no-issues p{font-size:11px;color:#8d9c8f;line-height:1.7}.campaign-team{margin-top:24px}.campaign-team .content-link{font-size:11px}.campaign-team-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.campaign-team-grid article{display:flex;align-items:center;gap:12px;border:1px solid #e6ece5;border-radius:9px;padding:16px;min-width:0}.campaign-avatar{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0;color:#3c7254;background:#e5eee6;font-size:11px;font-weight:600}.campaign-team-grid article>div{min-width:0}.campaign-team-grid strong{display:block;font-size:12px;font-weight:600;overflow-wrap:anywhere}.campaign-team-grid small{display:block;font-size:10px;color:#86988a;line-height:1.7;margin-top:5px}.campaign-method{font-size:10px;color:#95a197;line-height:1.8;margin:20px 0 0;border-top:1px solid #edf1eb;padding-top:15px}.campaign-empty{text-align:center;padding:50px 25px}.campaign-empty h2{font-size:24px}.campaign-empty p{max-width:530px;margin:16px auto 24px;font-size:13px;line-height:1.8;color:#849687}.campaign-empty-icon{background:#e8f2e9;width:60px;height:60px;border-radius:14px;display:flex;align-items:center;justify-content:center;margin:auto;color:#30714e}.campaign-empty-icon svg{width:30px;height:30px}
@media(max-width:1200px){.campaign-summary{grid-template-columns:1fr;gap:24px}.campaign-summary-metrics{max-width:650px}.campaign-grid{grid-template-columns:minmax(0,1.5fr) minmax(0,1fr)}.campaign-team-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:850px){.campaign-grid{grid-template-columns:1fr}.campaign-team-grid{grid-template-columns:1fr 1fr}.inventory-heading{align-items:flex-start}.campaign-summary h2{font-size:23px}}
@media(max-width:550px){.inventory-heading{flex-direction:column;gap:18px}.inventory-heading-actions{width:100%}.inventory-heading-actions .btn{flex:1;justify-content:center;font-size:11px}.campaign-summary{padding:22px 20px}.campaign-summary-metrics{gap:12px}.campaign-summary-metrics strong{font-size:26px;letter-spacing:-.7px}.campaign-summary-metrics strong>span{font-size:11px}.campaign-summary-metrics small{font-size:9px}.campaign-summary h2{font-size:22px}.campaign-primary-action{flex-direction:column;align-items:stretch;gap:8px}.campaign-primary-action .btn{justify-content:center}.campaign-team-grid{grid-template-columns:1fr}.campaign-issue{gap:9px}.campaign-progress-legend{gap:8px}.campaign-panel-title{gap:12px}.campaign-progress-legend>span{font-size:9px}.campaign-method{font-size:10px}}


.inv-details{margin-bottom:18px}.inv-details summary{cursor:pointer;font-weight:600;padding:12px 0}.inv-simple-metrics{display:grid!important;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.inv-simple-list{min-width:700px}.inv-simple-list .row-photo{width:44px;height:44px}.inv-simple-list .row-photo img{width:100%;height:100%;object-fit:cover}@media(max-width:650px){.inv-simple-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.inventory-action-panel{margin:16px 0}}

/* Paleta extraída da referência ICMBio enviada: alteração apenas visual. */
@media screen {
:root{--green:#004622;--accent:#37784d;--bg:#f5f8f2;--ink:#192d21;--muted:#586b5f;--line:#dce6d8;--icmbio-lime:#a0c517;--icmbio-olive:#598727;--icmbio-soft:#eef5e7}
body{background:var(--bg);color:var(--ink)}
.sidebar{background:#004622;color:#e6efdf}
.brand svg{color:#a0c517}.brand small{color:#d1e4b6}.brand strong{color:#fff}
.nav a,.nav-group summary,.logout-button{color:#e6efdf}
.nav a:hover,.nav-group summary:hover,.logout-button:hover{background:#ffffff12;color:#fff}
.nav a.active,.nav-group summary.active{background:#a0c51c21;color:#fff;box-shadow:inset 3px 0 0 #a0c517}
.nav a.active svg,.nav-group summary.active>svg:first-child{color:#c2df62}
.nav .nav-submenu a{color:#d4e6c9}.nav .nav-submenu a.selected{background:#a0c51c21;color:#fff;box-shadow:inset 2px 0 0 #a0c517}
.sidefoot{color:#c2d9b9}.sidebar-logout{border-color:#ffffff20}
.top{background:#fff;border-bottom-color:#dce6d8;box-shadow:0 2px 14px #00462204}
.avatar{background:#004622;color:#fff;box-shadow:0 0 0 3px #eef5e7}
h1,h2,h3{color:#123e25}.panel,.stat,.form-section,.analytics-kpi{background:#fff;border-color:#dce6d8;box-shadow:0 3px 14px #00462204}
.btn{color:#164c2b;border-color:#cdddc5;background:#fff}
.btn:hover{background:#eef5e7;border-color:#91b073}
.btn.primary,.registry-navigation a.current{background:#004622;color:#fff;border-color:#004622;box-shadow:0 3px 8px #00462218}
.btn.primary:hover,.registry-navigation a.current:hover{background:#0c5b31;border-color:#0c5b31;color:#fff}
.btn:disabled{opacity:.55;cursor:not-allowed}
.registry-navigation a:not(.current){color:#365a3c;border-color:#d5e2cd;background:#fff}
.stat>svg{background:#eef5e7;color:#37784d}.stat strong,.analytics-kpi>strong,.op-metrics strong{color:#004622}
.analytics-kpi:hover{border-color:#598727;box-shadow:0 5px 18px #0046220c}
.analytics-kpi-action,.text-action{color:#246136}
.analytics-track{background:#edf3e6}.analytics-track>span{background:#37784d}
.analytics-bar:nth-child(2n) .analytics-track>span{background:#598727}
.analytics-bar:nth-child(3n) .analytics-track>span{background:#004622}
.analytics-bar:nth-child(4n) .analytics-track>span{background:#a0c517}
.analytics-chart-title>span,.picker-state{background:#eef5e7;color:#365e27}
.badge:not(.warn){background:#eef5e7;color:#2d5b2d}
.feedback{background:#eef6e8;border-color:#ccdcbc;color:#234e2e}
input,select,textarea{border-color:#ccdaca}
input:focus,select:focus,textarea:focus{border-color:#37784d}
button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,summary:focus-visible{outline:3px solid #598727;outline-offset:3px}
.sidebar a:focus-visible,.sidebar button:focus-visible,.sidebar summary:focus-visible{outline-color:#c2df62}
input[type=checkbox],input[type=radio],progress{accent-color:#37784d}
thead th{background:#f0f5eb;color:#36543b;border-bottom-color:#dce6d8}
tbody tr:hover{background:#f7faf3}
.picker-origin,.callout,.op-selection-hint{background:#f1f6eb;border-color:#dce6d4;color:#36583d}
.picker-result:hover,.picker-result:focus-visible{background:#eef5e7}
.guide-node[aria-pressed=true]{background:#eef5e7;border-color:#598727;box-shadow:0 0 0 1px #598727}
.guide-node{background:#f8faf4;color:#365e27}
.inventory-read{background:#004622;color:#fff;border-color:#004622}
.inventory-read:hover{background:#0c5b31}.inventory-hero{background:#004622;color:#fff}
.inventory-hero h2{color:#fff}
}
/* Layout aprovado: cards compactos, gráficos e lista com fotos. */
@media screen {
:root{--bg:#f6f8f6;--line:#e0e7df;--muted:#637268}
.sidebar{background:#004622}.nav a.active,.nav-group summary.active{background:#22603c;box-shadow:inset 3px 0 0 #a0c517}
.nav a.active svg{color:#fff}.brand svg{color:#b4d935}
main{padding-top:24px}.panel{border-radius:9px;box-shadow:0 2px 10px #123f2605}
.global-search{display:flex;align-items:center;gap:10px;width:min(36vw,500px);padding:8px 12px;background:#f8faf8;border:1px solid #e0e6df;border-radius:7px;margin-left:auto}
.global-search svg{width:17px;height:17px;color:#627168;flex-shrink:0}.global-search input{border:0;background:transparent;width:100%;min-width:0;padding:2px;outline:none;font-size:12px}.global-search:focus-within{outline:2px solid #598727;outline-offset:2px}.top .profile{margin-left:18px}
.visually-hidden{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.home19-heading{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:20px}.home19-heading h1{font-size:32px;letter-spacing:-1px;margin:0 0 7px;color:#073e25}.home19-heading p{margin:0;color:#637268;font-size:13px;line-height:1.6}.home19-heading .dashboard-top-actions{display:flex;gap:10px;flex-shrink:0}.home19-heading .btn{min-height:41px;display:inline-flex;gap:9px;align-items:center;justify-content:center}
.home19-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin-bottom:18px}.home19-kpi{background:#fff;border:1px solid #e0e7df;border-radius:9px;box-shadow:0 2px 10px #123f2605;padding:18px 16px;min-width:0;display:flex;flex-direction:column;gap:13px}.home19-kpi:hover{border-color:#91b277}.home19-kpi-main{display:flex;align-items:center;gap:12px;min-width:0}.home19-kpi-main>div{min-width:0;flex:1}.home19-kpi-main>div>span{display:block;font-size:11px;line-height:1.5;color:#637268;margin-bottom:5px}.home19-kpi strong{display:block;font-size:29px;line-height:1.15;letter-spacing:-.7px;color:#004622;overflow-wrap:anywhere}.home19-kpi .home19-value{font-size:clamp(17px,1.55vw,25px)}.home19-kpi>small{font-size:10px;color:#637268;line-height:1.6}.home19-icon{width:46px;height:48px;border-radius:8px;background:#edf5e9;color:#00522c;display:flex;align-items:center;justify-content:center;flex-shrink:0}.home19-icon svg{width:25px;height:25px}.home19-icon.olive{background:#eff5e5;color:#4a721f}.home19-icon.amber{background:#fff5d7;color:#77601c}.home19-icon.red{background:#fde9e7;color:#b53c39}
.home19-charts{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr);gap:18px;margin-bottom:18px}.home19-chart{padding:20px;margin:0;min-width:0}.home19-chart h2,.home19-assets h2{font-size:18px;letter-spacing:-.4px;margin:0 0 6px}.home19-chart>p,.home19-section-title p{font-size:11px;color:#637268;line-height:1.6;margin:0}.home19-bars{display:flex;flex-direction:column;gap:18px;margin-top:24px}.home19-bar{display:grid;grid-template-columns:minmax(100px,35%) minmax(0,1fr) 30px;gap:12px;align-items:center;font-size:11px;color:#4c6253}.home19-bar>span{overflow-wrap:anywhere}.home19-bar>strong{text-align:right;color:#234332;font-size:12px}.home19-track{background:#f0f3ef;height:23px;border-radius:3px;overflow:hidden}.home19-track>i{display:block;height:100%;background:#00502c;border-radius:3px}.home19-bar:nth-child(2) i{background:#598e5c}.home19-bar:nth-child(3) i{background:#92b584}.home19-bar:nth-child(4) i{background:#c1d7af}.home19-bar:hover{color:#004622}
.home19-donut-layout{display:flex;align-items:center;justify-content:center;gap:15px;min-height:204px}.home19-donut{width:175px;height:175px;flex-shrink:0}.home19-donut-number{font:700 18px system-ui;fill:#123e25;stroke:none}.home19-donut-caption{font:12px system-ui;fill:#637268;stroke:none}.home19-legend{display:flex;flex-direction:column;gap:22px;flex:1;min-width:0}.home19-legend a{display:grid;grid-template-columns:10px 1fr auto auto;gap:9px;align-items:center;font-size:11px;color:#4d6253}.home19-legend i{display:block;width:10px;height:10px;border-radius:50%;background:#00502c}.home19-legend i.pending{background:#8aa52b}.home19-legend strong{font-size:11px;color:#234332}.home19-legend small{font-size:10px;color:#637268}
.home19-assets{padding:20px;margin-bottom:18px}.home19-section-title{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:18px}.home19-section-title>a{font-size:11px;white-space:nowrap}.home19-filters{display:flex;gap:10px;align-items:center;margin-bottom:14px}.home19-filters>div{flex:1;min-width:0}.home19-filters>div:first-child{flex:2}.home19-filters input,.home19-filters select{width:100%;height:39px;padding:9px 12px;border:1px solid #dce5d9;border-radius:6px;background:#fff;font-size:11px;color:#425948}.home19-filters .btn{height:39px}.home19-table{min-width:860px;width:100%;border-collapse:collapse}.home19-table th{font-size:10px;font-weight:600;background:#f0f4ef}.home19-table td{font-size:11px;padding-top:10px;padding-bottom:10px;border-color:#e9eee7}.home19-table .text-action{font-size:10px;white-space:nowrap;text-decoration:underline;text-underline-offset:3px}.home19-asset-name{display:flex;gap:12px;align-items:center;min-width:200px}.home19-asset-name strong{font-size:11px;font-weight:600;display:block;max-width:270px;overflow-wrap:anywhere}.home19-asset-name small{display:block;font-size:10px;color:#637268;margin-top:5px;max-width:270px;overflow-wrap:anywhere}.home19-thumb{width:42px;height:42px;border-radius:5px;background:#f0f3ed;display:flex;align-items:center;justify-content:center;overflow:hidden;flex-shrink:0;color:#78916e}.home19-thumb img{width:100%;height:100%;object-fit:cover}.home19-thumb svg{width:22px;height:22px}.home19-table .badge{font-size:10px;white-space:nowrap}.home19-scope{font-size:10px;color:#637268;margin:13px 0 0;line-height:1.6}.home19-attention{padding:16px 20px}.home19-attention>summary{font-size:13px;font-weight:600;cursor:pointer;color:#31573b}.home19-attention-links{display:flex;gap:15px;flex-wrap:wrap;margin:20px 0;font-size:12px}.home19-attention-links a{color:#246136;text-decoration:underline}.home19-attention h2{font-size:15px;margin-top:20px}
@media(max-width:1200px){.home19-donut-layout{flex-direction:column;gap:10px}.home19-donut{width:145px;height:145px}.home19-legend{width:100%;gap:10px}.home19-charts{grid-template-columns:minmax(0,1.2fr) minmax(0,1fr)}.home19-icon{width:36px;height:40px}.home19-kpi{padding:15px 12px}.home19-kpi-main{gap:8px}.home19-kpi .home19-value{font-size:18px}}
@media(max-width:1000px){.global-search{display:none}.home19-heading{align-items:flex-start}.home19-heading h1{font-size:28px}.home19-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.home19-kpi .home19-value{font-size:25px}.home19-heading .dashboard-top-actions{flex-wrap:wrap;justify-content:flex-end}.home19-heading .btn{font-size:11px}}
@media(max-width:700px){.home19-heading{flex-direction:column;gap:15px}.home19-heading .dashboard-top-actions{justify-content:flex-start;width:100%}.home19-heading .btn{flex:1}.home19-kpis{gap:10px}.home19-kpi{padding:14px 11px}.home19-kpi .home19-value{font-size:18px}.home19-kpi strong{font-size:25px}.home19-kpi-main{align-items:flex-start}.home19-icon{width:32px;height:36px}.home19-icon svg{width:21px;height:21px}.home19-charts{grid-template-columns:1fr}.home19-donut-layout{flex-direction:row}.home19-donut{width:155px;height:155px}.home19-legend{gap:20px}.home19-chart,.home19-assets{padding:17px}.home19-filters{flex-wrap:wrap}.home19-filters>div:first-child{flex-basis:100%}.home19-filters>div{min-width:120px}.home19-filters input,.home19-filters select{font-size:16px}.home19-bar{grid-template-columns:minmax(90px,38%) 1fr 28px;gap:9px}.home19-section-title{align-items:flex-start}.top .profile{margin-left:auto}}
}

/* Paleta definida pelo usuário, aplicada sem mudar o layout. */
@media screen {

:root {
  --verde-menu:     #0B3325;
  --verde-escuro:   #0E3B2B;
  --verde-logo:     #14513A;
  --verde:          #15573F;
  --verde-medio:    #6FCF97;
  --verde-limao:    #C7F26B;
  --verde-claro:    #E1F0E6;
  --fundo:          #F4F5F1;
}

:root{--green:var(--verde-escuro);--accent:var(--verde);--bg:var(--fundo);--icmbio-lime:var(--verde-limao);--icmbio-soft:var(--verde-claro)}
body{background:var(--fundo)}
.sidebar{background:var(--verde-menu)}
.brand svg{background:var(--verde-logo);color:var(--verde-limao);border-radius:9px;padding:5px}
.nav a.active,.nav-group summary.active{background:var(--verde-logo);box-shadow:inset 3px 0 0 var(--verde-limao)}
.nav .nav-submenu a.selected{background:var(--verde-logo);box-shadow:inset 2px 0 0 var(--verde-limao)}
.sidebar a:focus-visible,.sidebar button:focus-visible,.sidebar summary:focus-visible{outline-color:var(--verde-limao)}
.avatar{background:var(--verde-limao);color:var(--verde-menu);box-shadow:0 0 0 3px var(--verde-claro)}
.btn.primary,.registry-navigation a.current,.inventory-read,.inventory-hero,.campaign-summary{background:var(--verde-escuro);border-color:var(--verde-escuro);color:#fff}
.btn.primary:hover,.registry-navigation a.current:hover,.inventory-read:hover{background:var(--verde);border-color:var(--verde);color:#fff}
.btn:not(.primary),.text-action,.content-link,.analytics-kpi-action{color:var(--verde)}
.content-link,.content-link:visited,.home19-table .text-action{color:var(--verde);text-decoration:underline;text-underline-offset:3px}
.btn:not(.primary):hover,.picker-result:hover,.picker-result:focus-visible{background:var(--verde-claro)}
.home19-kpi strong,.analytics-kpi>strong,.stat strong{color:var(--verde-escuro)}
.home19-icon:not(.amber):not(.red),.badge:not(.warn),.stat>svg,.campaign-empty-icon{background:var(--verde-claro);color:var(--verde)}
.home19-track>i,.analytics-track>span,.seg-conferido{background:var(--verde)}
.home19-bar:nth-child(2) i{background:var(--verde-medio)}
.home19-bar:nth-child(3) i{background:var(--verde-logo)}
.home19-bar:nth-child(4) i{background:var(--verde-limao)}
.home19-donut circle:nth-of-type(2){stroke:var(--verde-limao)}
.home19-donut circle:nth-of-type(3){stroke:var(--verde)}
.home19-legend i{background:var(--verde)}.home19-legend i.pending{background:var(--verde-limao)}
.analytics-bar:nth-child(2n) .analytics-track>span{background:var(--verde-medio)}
.analytics-bar:nth-child(3n) .analytics-track>span{background:var(--verde-logo)}
.analytics-bar:nth-child(4n) .analytics-track>span{background:var(--verde-limao)}
.analytics-bar[data-paleta="global-iii"] .analytics-track>span{background:var(--verde-medio)}
.analytics-bar[data-paleta="horizontes"] .analytics-track>span{background:var(--verde-limao)}
input[type=checkbox],input[type=radio],progress{accent-color:var(--verde)}
.guide-node[aria-pressed=true]{background:var(--verde-claro);border-color:var(--verde);box-shadow:0 0 0 1px var(--verde)}
.feedback,.op-selection-hint{background:var(--verde-claro);color:var(--verde-escuro)}
}

/* Inventário: resumo compacto e um único ponto de busca. */
@media screen {
.inv-clean-heading{align-items:center;margin-bottom:18px}.inv-clean-heading p{margin-bottom:0}
.inv-clean-heading-actions{display:flex;gap:10px;flex-wrap:wrap;justify-content:flex-end}
.inv-clean-metrics{gap:12px;margin-bottom:18px}.inv-clean-metrics>article{padding:14px 18px;display:flex;flex-direction:column;gap:7px;min-height:76px}
.inv-clean-metrics>article>span{font-size:11px}.inv-clean-metrics>article>strong{font-size:25px;line-height:1.1}
.inv-clean-list{padding:20px;margin-bottom:0}.inv-clean-toolbar{display:grid;grid-template-columns:minmax(150px,1fr) minmax(210px,1.5fr) minmax(135px,.7fr) auto auto;gap:12px;align-items:end}
.inv-clean-toolbar .field{min-width:0}.inv-clean-toolbar label{font-size:11px;margin-bottom:7px;display:block}
.inv-clean-toolbar input,.inv-clean-toolbar select{height:42px;width:100%;padding:10px 12px;border:1px solid #ccdaca;border-radius:6px;background:#fff;font-size:12px}
.inv-clean-toolbar .btn{height:42px;min-height:42px;white-space:nowrap;display:inline-flex;align-items:center;justify-content:center;gap:8px;margin:0}
.inv-clean-toolbar .inv-qr{border-color:var(--verde);color:var(--verde);background:#fff}.inv-clean-toolbar .inv-qr svg{width:17px;height:17px}
.inv-clean-list-info{display:flex;justify-content:space-between;align-items:center;gap:12px;font-size:11px;color:#586b5f;padding:15px 0}
.inv-clean-note{font-size:10px;color:#586b5f;line-height:1.7;margin:12px 0 20px}
.inv-clean-options{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.inv-clean-details{padding:12px 18px;margin:0;min-width:0;align-self:start}.inv-clean-details>summary{cursor:pointer;font-size:12px;font-weight:600;padding:4px 0;color:var(--verde)}.inv-clean-details>p{font-size:12px;line-height:1.7}.inv-clean-details .op-section{padding:0;margin:18px 0 0;border:0;box-shadow:none}
@media(max-width:1150px){.inv-clean-toolbar{grid-template-columns:minmax(140px,1fr) minmax(170px,1.3fr) minmax(130px,.8fr)}.inv-clean-toolbar .inv-filter-button{grid-column:2;grid-row:2}.inv-clean-toolbar .inv-qr{grid-column:3;grid-row:2}}
@media(max-width:700px){.inv-clean-heading{align-items:flex-start;gap:14px;flex-direction:column}.inv-clean-heading-actions{width:100%;justify-content:flex-start}.inv-clean-heading-actions .btn{flex:1;justify-content:center;font-size:11px}.inv-clean-metrics{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.inv-clean-metrics>article{padding:12px 14px;min-height:70px}.inv-clean-list{padding:16px}.inv-clean-toolbar{grid-template-columns:1fr 1fr;gap:12px}.inv-clean-toolbar>.field:first-child{grid-column:1/-1}.inv-clean-toolbar>.field:nth-child(2){grid-column:1/-1}.inv-clean-toolbar>.field:nth-child(3){grid-column:1}.inv-clean-toolbar .inv-filter-button{grid-column:2;grid-row:auto;align-self:end}.inv-clean-toolbar .inv-qr{grid-column:1/-1;grid-row:1;background:var(--verde-escuro);color:#fff;border-color:var(--verde-escuro);height:46px}.inv-clean-toolbar input,.inv-clean-toolbar select{font-size:16px}.inv-clean-options{grid-template-columns:1fr}}
}

@media screen{.sidebar .brand>div{min-width:0}.sidebar .brand strong{display:block;font-size:20px;line-height:1.12;letter-spacing:-.5px;white-space:normal}.sidebar .brand small{font-size:8px;letter-spacing:.6px;line-height:1.6}.sidebar .brand svg{flex-shrink:0}}

@media screen{.inv-top-data{margin:0 0 16px}.inv-top-data>p{margin:8px 0}.inv-top-data>.text-action{display:inline-block;margin-top:3px}}
.mobile-home,.mobile-bottom-nav{display:none}
@media screen and (max-width:768px){
body{font-family:'Geist',system-ui,sans-serif;background:#F4F5F1}
.sidebar{transform:translateX(-100%);width:270px;max-width:85vw;z-index:50;transition:transform .2s}.sidebar.open{transform:translateX(0)}.shell{margin-left:0}.btn.mobile{display:inline-flex;min-height:48px}.menu-overlay.open{display:block;position:fixed;inset:0;z-index:45;background:#0b332577;border:0}
body.mobile-dashboard-page .top,body.mobile-dashboard-page main>footer,body.mobile-dashboard-page .desktop-overview{display:none}
body.mobile-dashboard-page main{padding:0!important;max-width:none;margin:0;min-height:100dvh}
body.mobile-dashboard-page .feedback{margin:12px 14px}
.mobile-home{display:block;background:#F4F5F1;padding-bottom:calc(100px + env(safe-area-inset-bottom,0px));min-height:100dvh;color:#172b20}
.mh-header{background:#0B3325;color:white;padding:calc(22px + env(safe-area-inset-top,0px)) 22px 66px}
.mh-brand-row{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:24px}
.mh-brand{display:flex;align-items:center;gap:9px;color:#fff;min-height:48px}.mh-brand>svg{width:25px;height:29px;flex-shrink:0;color:#C7F26B;padding:4px;border-radius:7px;background:#14513A}.mh-brand strong{font-size:16px;letter-spacing:.1px;line-height:1.15;display:block}.mh-brand small{font-size:8px;letter-spacing:1.3px;display:block;margin-top:4px;color:#e6f0e8}
.mh-avatar{display:flex;align-items:center;justify-content:center;width:38px;height:38px;background:#C7F26B;color:#0B3325;font-size:13px;font-weight:700;border-radius:50%;flex-shrink:0}
.mh-greeting{font-size:13px;color:#c4d6cb;margin:0 0 5px;line-height:1.6}.mh-total{display:flex;gap:8px;align-items:baseline}.mh-total>strong{font-size:44px;line-height:1.05;letter-spacing:-1.8px;font-weight:650}.mh-total>span{font-size:14px;color:#d7e6dd}.mh-totals{font-size:11px;color:#d7e6dd;line-height:1.7;margin:8px 0 0;overflow-wrap:anywhere}
.mh-content{padding:0 16px;margin-top:-44px;position:relative}.mh-card{background:#fff;border:1px solid #E5E7E1;border-radius:18px;min-width:0}.mh-inventory{padding:17px 16px 16px;box-shadow:0 9px 22px #0b33251c;margin-bottom:13px}.mh-progress-row{display:flex;align-items:center;gap:13px;margin-bottom:15px}.mh-progress{position:relative;width:65px;height:65px;flex-shrink:0}.mh-progress svg{width:65px;height:65px;fill:none;stroke:none}.mh-progress circle{fill:none;stroke:#edf0e9;stroke-width:6}.mh-progress circle.mh-progress-fill{stroke:#15573F;stroke-linecap:round}.mh-progress>strong{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:700;color:#172b20}.mh-inventory-text{min-width:0}.mh-inventory-text>small{font-size:11px;color:#6b7c70;line-height:1.5}.mh-inventory-text>h2{font-size:14px;line-height:1.45;font-weight:650;margin:3px 0 5px;color:#172b20;overflow-wrap:anywhere}.mh-inventory-text>p{font-size:11px;color:#586c5e;margin:0;line-height:1.6}
.mh-primary{min-height:48px;border:0;border-radius:11px;background:#0E3B2B;color:#fff;display:flex;align-items:center;justify-content:center;gap:9px;width:100%;padding:12px 14px;font:600 13px 'Geist',system-ui,sans-serif;text-align:center;line-height:1.4}.mh-primary>svg{width:18px;height:18px;color:#C7F26B;flex-shrink:0}
.mh-attention{padding:15px 15px 11px;margin-bottom:13px}.mh-attention-title{display:flex;align-items:center;gap:10px;margin-bottom:6px}.mh-check{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;flex-shrink:0;border-radius:50%;background:#E1F0E6;color:#15573F}.mh-check>svg{width:13px;height:13px}.mh-attention-title>.mh-check{width:28px;height:28px}.mh-attention-title h2{font-size:14px;font-weight:650;margin:0;color:#172b20}.mh-attention-title p{font-size:10px;color:#6c7c70;margin:3px 0 0}
.mh-status-grid{display:grid;grid-template-columns:1fr 1fr;gap:3px 8px}.mh-status{display:flex;align-items:center;gap:7px;font-size:11px;color:#3f5747;min-height:48px;border-radius:10px;padding:5px 3px;line-height:1.4}.mh-status small{display:block;font-size:10px;margin-top:3px}.mh-warning{background:#FDF3E7;color:#8A3E05}.mh-danger{background:#FCE8E6;color:#B42318}.mh-warning .mh-check{background:#fbe5ca;color:#8A3E05}.mh-danger .mh-check{background:#f8d2cd;color:#B42318}
.mh-actions{display:grid;grid-template-columns:1fr 1fr;gap:11px}.mh-actions>a{display:flex;flex-direction:column;align-items:flex-start;justify-content:space-between;padding:14px 16px;gap:19px;min-height:90px;color:#172b20}.mh-actions svg{width:20px;height:20px;color:#15573F}.mh-actions>a>span{font-size:24px;color:#15573F;line-height:20px}.mh-actions strong{font-size:12px;font-weight:650}
.mobile-bottom-nav{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));position:fixed;bottom:0;left:0;right:0;background:#fff;border-top:1px solid #E5E7E1;padding:5px 6px calc(5px + env(safe-area-inset-bottom,0px));z-index:40;min-height:68px;box-shadow:0 -2px 12px #0b332506}
.mobile-bottom-nav>a,.mobile-bottom-nav>button{min-width:0;min-height:54px;background:none;border:0;color:#6b7b70;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;font:400 10px 'Geist',system-ui,sans-serif;padding:4px 0;line-height:1.3}.mobile-bottom-nav svg{width:20px;height:20px}.mobile-bottom-nav .current{color:#15573F;font-weight:650}.mobile-bottom-nav .mobile-nav-qr{justify-content:flex-start;position:relative;padding:0}.mobile-nav-qr>span{width:54px;height:54px;border-radius:50%;background:#0E3B2B;color:#C7F26B;display:flex;align-items:center;justify-content:center;position:relative;margin-top:-20px;box-shadow:0 4px 10px #0b33252b;border:4px solid #F4F5F1;box-sizing:content-box}.mobile-nav-qr>span>svg{width:24px;height:24px}
.shell>main{padding-bottom:calc(95px + env(safe-area-inset-bottom,0px))}.sidebar a,.sidebar button,.sidebar summary{min-height:48px;box-sizing:border-box}
.mh-camera{width:calc(100% - 28px);max-width:500px;border:1px solid #E5E7E1;border-radius:18px;padding:18px;color:#172b20;background:white}.mh-camera::backdrop{background:#0b3325b8}.mh-camera-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.mh-camera-heading h2{font-size:18px}.mh-camera .btn{min-height:48px}.mh-camera video{width:100%;background:#0B3325;border-radius:12px;min-height:160px;max-height:42dvh;object-fit:cover;margin-top:12px}.mh-camera p{font-size:13px;line-height:1.6}.mh-camera form label{display:block;font-size:12px;margin:14px 0 8px}.mh-camera form>div{display:flex;flex-wrap:wrap;gap:10px}.mh-camera input{min-width:0;width:100%;font-size:16px;min-height:48px;border:1px solid #ccdaca;border-radius:9px;padding:10px}
}
@media screen and (min-width:769px){.mh-camera{display:none}}
@media print{.mobile-home,.mobile-bottom-nav,.mh-camera{display:none!important}}

/* Versão 3.2 — organização institucional compacta; celular preservado. */
.nav-section-label{display:block;font-size:10px;letter-spacing:1.5px;color:#a2bdae;padding:18px 12px 8px}
.home25-shortcuts{margin:24px 0}.home25-shortcuts h2{font-size:15px;margin:0 0 12px}
.home25-shortcut-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.home25-shortcut-grid>a{display:flex;align-items:center;gap:12px;min-height:84px;padding:16px;border:1px solid #E5E7E1;border-radius:12px;background:white;color:#183f30;text-decoration:none}
.home25-shortcut-grid>a:hover{border-color:var(--verde)}.home25-shortcut-grid>a>div{flex:1;min-width:0}.home25-shortcut-grid strong{font-size:13px;display:block}.home25-shortcut-grid small{font-size:12px;line-height:1.5;display:block;color:#637268;margin-top:5px}
.home25-shortcut-icon{display:grid;place-items:center;width:38px;height:38px;flex:none;background:var(--verde-claro);border-radius:9px;color:var(--verde)}.home25-shortcut-icon svg{width:20px;height:20px}
.home25-workspace{display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:18px;align-items:start}.home25-workspace>.home19-assets{min-width:0}.home25-aside{display:grid;gap:16px;min-width:0}
.home25-inventory{background:var(--verde-escuro);color:white;padding:22px;border-radius:14px}.home25-inventory h2{font-size:19px;color:white;overflow-wrap:anywhere;margin:14px 0 5px}.home25-inventory small{font-size:12px;line-height:1.6;color:#d2e4d9;display:block}.home25-inventory p{font-size:12px;color:#d2e4d9;line-height:1.6}.home25-percent{display:flex;align-items:baseline;gap:10px;margin-top:20px}.home25-percent strong{font-size:32px}.home25-percent span{font-size:12px}.home25-inventory progress{width:100%;height:8px;border:0;border-radius:9px;overflow:hidden;background:#4c6c5b;accent-color:var(--verde-limao)}.home25-inventory progress::-webkit-progress-bar{background:#4c6c5b}.home25-inventory progress::-webkit-progress-value{background:var(--verde-limao)}.home25-inventory progress::-moz-progress-bar{background:var(--verde-limao)}.home25-inventory .btn{display:flex;justify-content:center;min-height:44px;background:var(--verde-limao);color:var(--verde-menu);border:0;margin:15px 0;font-size:13px}
.home25-pending{padding:18px}.home25-pending h2{font-size:15px;margin:0 0 10px}.home25-pending>a{display:flex;align-items:center;gap:9px;padding:14px 0;border-bottom:1px solid #E5E7E1;color:var(--verde);text-decoration:none;font-size:12px;line-height:1.5}.home25-pending>a:last-child{border:0}.home25-pending>a>div{flex:1}.home25-pending svg{width:18px;height:18px}.home25-pending .has-pending{color:#8A3E05}.home25-pending .has-pending>span:first-child{background:#FDF3E7}.home25-pending .is-overdue{color:#B42318}.home25-pending .is-overdue>span:first-child{background:#FCE8E6}.home25-pending>a>span:first-child{display:grid;place-items:center;width:30px;height:30px;border-radius:7px;background:var(--verde-claro);flex:none}
@media(min-width:769px){
.sidebar{width:224px;padding:20px 12px}.shell{margin-left:224px}.sidebar .brand{padding:0 8px 18px;gap:8px}.sidebar .brand strong{font-size:19px}.sidebar .brand strong br{display:none}.sidebar .brand small{font-size:9px;letter-spacing:0}.nav{gap:3px}.nav a,.nav-group summary{font-size:13px;padding:11px 12px;min-height:40px}.nav a.active{background:var(--verde-limao);color:var(--verde-menu);box-shadow:none}.nav a.active svg{color:var(--verde-menu)}.nav-submenu a{font-size:12px}.sideart{display:none}.sidefoot{margin-top:24px}.sidebar-logout{margin-top:12px;border-top:1px solid #ffffff20;padding-top:12px}
.top{height:64px;background:var(--verde-escuro);border-bottom:1px solid #ffffff12;color:#eef5ef;gap:16px;padding:0 26px}.top .crumb{font-size:12px;color:#d6e6dc}.top .profile{color:white;font-size:13px}.top .profile small{color:#c2d7cb}.top .avatar{background:var(--verde-limao);color:var(--verde-menu)}.top .global-search{background:#ffffff0d;border:1px solid #ffffff26;max-width:340px}.top .global-search input{color:white}.top .global-search input::placeholder{color:#bad0c1}.top .global-search svg{color:#bad0c1}
.shell>main{padding:26px;max-width:1900px}.desktop-overview .home19-heading h1{font-size:28px}.desktop-overview .home19-heading p{font-size:13px}.desktop-overview .home19-kpi{border-color:#E5E7E1;border-radius:14px;box-shadow:none;padding:18px}.desktop-overview .home19-kpi-main{flex-direction:row-reverse;align-items:flex-start}.desktop-overview .home19-kpi-main>div>span{font-size:12px}.desktop-overview .home19-kpi>small{font-size:12px}.desktop-overview .home19-icon{width:32px;height:32px}.desktop-overview .home19-icon svg{width:19px;height:19px}.desktop-overview .home19-value{font-size:clamp(21px,1.7vw,29px)}.desktop-overview .home19-assets{border:1px solid #E5E7E1;border-radius:14px;padding:18px}.desktop-overview .home19-table{min-width:720px}.desktop-overview .home19-table th{background:white;font-size:12px}.desktop-overview .home19-table td{font-size:12px;padding:12px 8px}.desktop-overview .home19-asset-name strong{font-size:12px}.desktop-overview .home19-asset-name{min-width:160px;gap:9px}.desktop-overview .home19-asset-name small{font-size:11px}.desktop-overview .home19-scope{font-size:12px}.desktop-overview .home19-filters{flex-wrap:wrap}.desktop-overview .home19-filters>div{min-width:120px}.desktop-overview .home19-filters input,.desktop-overview .home19-filters select{font-size:12px}.desktop-overview .home19-thumb{width:36px;height:36px}.desktop-overview .home19-table .text-action{font-size:12px}.desktop-overview .home19-attention{margin-top:18px}
}
@media(min-width:769px) and (max-width:1200px){.home25-workspace{grid-template-columns:minmax(0,1fr)}.home25-aside{grid-template-columns:1fr 1fr}.home25-shortcut-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}


/* Conferência de inventário em campo, sem alterar o acervo por leitura. */
.field27-wrap{width:100%;max-width:760px;margin:0 auto}.field27-title{margin:16px 0 22px}.field27-title h1{font-size:28px;line-height:1.2;margin:10px 0}.field27-title p{font-size:14px;line-height:1.6;color:#637268}.field27-message{background:#FDF3E7;border:1px solid #ecd8bd;color:#8A3E05;padding:16px;border-radius:12px;margin:16px 0;font-size:14px;line-height:1.6}.field27-message p{margin-bottom:0}.field27-context{margin-bottom:18px}.field27-context strong{display:block;font-size:18px}.field27-context small{display:block;margin-top:6px;color:#637268}.field27-context p{font-size:13px;color:#637268}.field27-start .field{margin-bottom:18px}.field27-start input,.field27-start select{width:100%;min-height:48px;font-size:16px}.field27-start .btn{min-height:48px}.field27-camera{width:100%;justify-content:center;margin:20px 0 5px}.field27-asset{display:grid;grid-template-columns:100px minmax(0,1fr);gap:18px;align-items:center;margin-bottom:18px}.field27-photo{width:100px;height:100px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;background:var(--verde-claro);border-radius:12px;overflow:hidden;color:var(--verde);font-size:10px}.field27-photo img{width:100%;height:100%;object-fit:contain;background:white}.field27-photo svg{width:30px;height:30px}.field27-plaque{font-size:13px;color:var(--verde);font-weight:600;overflow-wrap:anywhere}.field27-asset h2{font-size:21px;line-height:1.4;overflow-wrap:anywhere;margin:8px 0}.field27-asset p{font-size:13px;color:#637268;margin:5px 0;overflow-wrap:anywhere}.field27-asset dl{grid-column:1/-1;display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:4px 0}.field27-asset dt{font-size:12px;color:#637268;margin-bottom:5px}.field27-asset dd{margin:0;font-size:14px;font-weight:500;overflow-wrap:anywhere}.field27-asset>a{grid-column:1/-1;font-size:13px}.field27-form h2{font-size:18px;margin-bottom:18px}.field27-choices{display:grid;gap:12px}.field27-choice{display:flex;align-items:center;gap:14px;min-height:80px;border:1px solid #d7dfd5;padding:16px;border-radius:12px;cursor:pointer}.field27-choice:has(input:checked){border:2px solid var(--verde);padding:15px;background:var(--verde-claro)}.field27-choice input{width:22px;height:22px;min-height:22px;flex:none;accent-color:var(--verde)}.field27-choice strong{display:block;font-size:16px}.field27-choice small{display:block;font-size:13px;line-height:1.6;color:#637268;margin-top:3px}.field27-observation{margin:22px 0}.field27-observation label{display:block;font-size:14px;margin-bottom:10px}.field27-observation textarea{width:100%;min-height:112px;font-size:16px}.field27-observation small{font-size:12px;line-height:1.6;color:#637268}.field27-save{width:100%;min-height:52px;display:flex;justify-content:center;margin-top:12px;font-size:14px}
@media(max-width:768px){.field27-wrap .panel{padding:18px;border-radius:18px}.field27-title h1{font-size:26px}.field27-asset{grid-template-columns:80px minmax(0,1fr);gap:14px}.field27-photo{width:80px;height:90px}.field27-asset h2{font-size:19px}.field27-asset dl{gap:14px}.field27-choice{padding:14px}.field27-choice:has(input:checked){padding:13px}.field27-wrap .back{display:inline-flex;align-items:center;min-height:44px}}


/* v2.8 — título fixo no menu; somente a navegação rola. */
.sidebar{overflow:hidden;max-height:100vh;height:100vh;box-sizing:border-box}
@supports(height:100dvh){.sidebar{height:100dvh;max-height:100dvh}}
.sidebar .brand{flex:0 0 auto;min-width:0;max-width:100%;margin:0;align-items:center;padding:0 8px 18px}
.sidebar .brand>div{flex:1;min-width:0}.sidebar .brand strong{font-size:20px;line-height:1.15;letter-spacing:-.4px;white-space:normal;overflow-wrap:normal}.sidebar .brand strong>span{display:block}.sidebar .brand small{display:block;font-size:9px;line-height:1.6;letter-spacing:0;white-space:normal}.sidebar .brand>svg{width:34px;height:36px;flex:0 0 34px}
.sidebar .nav{flex:1 1 auto;min-height:0;overflow-y:auto;overflow-x:hidden;align-content:start;scrollbar-gutter:stable;scrollbar-width:thin;scrollbar-color:#638675 transparent;padding:0 5px 6px 0;overscroll-behavior:contain}
.sidebar .nav::-webkit-scrollbar{width:6px}.sidebar .nav::-webkit-scrollbar-thumb{background:#638675;border-radius:8px}.sidebar .nav::-webkit-scrollbar-track{background:transparent}
.sidebar .nav>a,.sidebar .nav-group summary,.sidebar .nav-submenu a{line-height:1.45;min-width:0;overflow-wrap:break-word}.sidebar .nav a>svg,.sidebar .nav-group summary>svg{flex-shrink:0}.sidebar .sideart{display:none}.sidebar .sidefoot{flex:0 0 auto;margin:8px 0 0;padding:8px;font-size:9px;line-height:1.5}
/* Colunas verticais, barras horizontais e roscas: todos por quantidade. */
.r28-column-scroll{overflow-x:auto;overflow-y:hidden;max-width:100%;padding:26px 5px 4px;scrollbar-width:thin;overscroll-behavior-x:contain}
.r28-columns{display:grid;grid-template-columns:repeat(var(--r28-count),minmax(100px,1fr));min-width:calc(var(--r28-count)*100px);gap:14px;padding:0 7px}
.r28-column{display:grid;grid-template-rows:210px minmax(64px,auto);color:var(--verde-escuro);text-decoration:none;min-width:0;border-radius:7px;outline-offset:2px}
.r28-column-frame{height:210px;display:flex;align-items:flex-end;justify-content:center;background:repeating-linear-gradient(to top,#e7ece5 0,#e7ece5 1px,transparent 1px,transparent 52.5px);border-bottom:1px solid #b6c7ba}
.r28-column-fill{position:relative;min-height:2px;width:60%;max-width:66px;border-radius:7px 7px 0 0;background:var(--verde);transition:filter .15s}
.r28-column:nth-child(3n+2) .r28-column-fill{background:var(--verde-medio)}.r28-column:nth-child(3n) .r28-column-fill{background:var(--verde-limao)}.r28-column:hover .r28-column-fill{filter:brightness(.9)}
.r28-column-fill>strong{position:absolute;bottom:100%;left:0;right:0;text-align:center;font-size:14px;color:var(--verde-escuro);padding-bottom:7px;font-variant-numeric:tabular-nums}
.r28-column>span{display:block;text-align:center;font-size:12px;line-height:1.5;padding:12px 4px 0;overflow-wrap:anywhere}
.r28-column-hint{font-size:11px;line-height:1.6;color:#637268;margin:12px 0 0}.r28-legend-other{display:flex;align-items:center;gap:9px;font-size:11px;line-height:1.5}.r28-legend-other>span:nth-child(2){flex:1}.r28-categorias .analytics-legend>*,.r28-categorias .analytics-legend>a>span:nth-child(2){min-width:0;overflow-wrap:anywhere}
@media(max-width:550px){.r28-columns{grid-template-columns:repeat(var(--r28-count),minmax(96px,1fr));min-width:calc(var(--r28-count)*96px);gap:10px}.r28-column>span{font-size:12px}.r28-column-fill>strong{font-size:15px}.r28-categorias .analytics-legend{gap:13px}.r28-categorias .analytics-legend a,.r28-legend-other{font-size:12px}.sidebar .brand strong{font-size:20px}}


/* Separadores visíveis entre linhas e colunas na seleção de plaquetas. */
.plaques29-grid{margin-top:22px;border-radius:8px}.plaques29-grid table{width:100%;border-collapse:collapse;border:1px solid #ABC1B1}.plaques29-grid th,.plaques29-grid td{border:1px solid #ABC1B1!important;padding:14px 12px!important;vertical-align:middle}.plaques29-grid th{background:#E1F0E6;color:#0E3B2B;font-size:12px;font-weight:650}.plaques29-grid td{font-size:13px}.plaques29-grid tbody tr:nth-child(even){background:#F8FAF6}.plaques29-grid tbody tr:hover{background:#EDF5EE}.plaques29-grid th:first-child,.plaques29-grid td:first-child{width:105px;text-align:center}.plaques29-grid input[type=checkbox]{accent-color:var(--verde);width:18px;height:18px}

/* 3.0 — detalhe do inventário: mesmos dados, filtros, rotas e regras. */
.inventory30-page{font-family:'Geist',system-ui,sans-serif}.inv30-page{width:100%;color:#173c2b}.inv30-page .btn{min-height:40px;height:auto;padding:9px 13px;font:500 12px 'Geist',system-ui;border-radius:8px;gap:7px;white-space:nowrap}.inv30-page .btn.primary{background:#0E3B2B;color:white;border-color:#0E3B2B}.inv30-page .btn svg{width:16px;height:16px;flex:none}.inv30-page .primary svg{color:#C7F26B}.inv30-heading{display:flex;align-items:center;justify-content:space-between;gap:20px;margin:0 0 22px}.inv30-title{display:flex;align-items:center;flex-wrap:wrap;gap:12px}.inv30-title h1{font-size:28px;font-weight:650;line-height:1.25;letter-spacing:-.7px;margin:0;overflow-wrap:anywhere}.inv30-heading>div>p{font-size:12px;color:#6a7e70;margin:10px 0 0}.inv30-heading-actions{display:flex;align-items:center;flex-wrap:wrap;gap:8px}.inv30-more{position:relative}.inv30-more summary{list-style:none;cursor:pointer;font-size:20px!important;padding:5px 12px!important}.inv30-more summary::-webkit-details-marker{display:none}.inv30-more>div{position:absolute;right:0;top:calc(100% + 7px);background:white;border:1px solid #E5E7E1;border-radius:10px;min-width:170px;padding:6px;z-index:5;box-shadow:0 8px 24px #0b33251a}.inv30-more a{display:block;padding:12px;font-size:13px;color:#15573F}.inv30-more a:hover{background:#E1F0E6;border-radius:6px}
.inv30-badge{display:inline-flex;align-items:center;gap:5px;border-radius:20px;padding:5px 9px;font-size:11px;font-weight:500;line-height:1.3;white-space:nowrap}.inv30-badge svg{width:11px;height:11px}.inv30-badge.pending{background:#FDF3E7;color:#8A3E05}.inv30-badge.checked{background:#E1F0E6;color:#15573F}.inv30-badge.occurrence{background:#FCE8E6;color:#B42318}.inv30-badge.closed{background:#ebefea;color:#526657}
.inv30-progress{display:grid;grid-template-columns:minmax(240px,31%) minmax(0,1fr);gap:28px;padding:25px 28px;background:#0E3B2B;border-radius:20px;color:white;margin-bottom:24px}.inv30-progress-summary{display:flex;align-items:center;gap:18px;border-right:1px solid #ffffff20;padding-right:20px}.inv30-ring{position:relative;flex:none;width:94px;height:94px}.inv30-ring svg{display:block;width:100%;height:100%}.inv30-ring circle{fill:none;stroke:#ffffff28;stroke-width:7}.inv30-ring .inv30-ring-value{stroke:#C7F26B;stroke-linecap:round}.inv30-ring>strong{position:absolute;inset:0;display:grid;place-items:center;font-size:23px;font-weight:650}.inv30-progress-summary small{font-size:11px;color:#c1d5c8}.inv30-progress-summary h2{font-size:23px;font-weight:600;color:white;margin:6px 0;line-height:1.25}.inv30-progress-summary p{font-size:12px;color:#c1d5c8;margin:0;line-height:1.5}.inv30-progress-detail{min-width:0;display:flex;flex-direction:column;justify-content:center}.inv30-progress-detail dl{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px;margin:0 0 20px}.inv30-progress-detail dt{font-size:10px;color:#abc6b6;margin-bottom:7px}.inv30-progress-detail dd{font-size:12px;line-height:1.6;color:#fff;margin:0;overflow-wrap:anywhere}.inv30-deadline{display:inline-block;font-size:9px;font-weight:600;padding:2px 6px;border-radius:5px;margin-left:5px}.inv30-deadline.today{background:#F2B544;color:#3D2600}.inv30-deadline.overdue{background:#FCE8E6;color:#B42318}.inv30-segments{display:flex;height:8px;border-radius:8px;overflow:hidden;background:#ffffff20}.inv30-segments>span{height:100%}.inv30-segments .checked,.inv30-legend .checked{background:#C7F26B}.inv30-segments .pending,.inv30-legend .pending{background:#4a7762}.inv30-segments .occurrence,.inv30-legend .occurrence{background:#F2B544}.inv30-legend{display:flex;flex-wrap:wrap;gap:16px;margin-top:9px}.inv30-legend>span{display:flex;align-items:center;gap:6px;font-size:10px;color:#c9dbcf}.inv30-legend i{display:block;width:7px;height:7px;border-radius:1px}
.inv30-list{background:white;border:1px solid #E5E7E1;border-radius:16px;overflow:hidden}.inv30-toolbar{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:18px 20px 14px;flex-wrap:wrap}.inv30-tabs{display:flex;align-items:center;gap:4px;background:#F4F5F1;padding:4px;border-radius:9px;max-width:100%;overflow-x:auto}.inv30-tabs>a{display:inline-flex;align-items:center;gap:7px;color:#64786b;padding:7px 10px;border-radius:6px;font-size:12px;white-space:nowrap;min-height:32px}.inv30-tabs>a.selected{background:#fff;color:#153d2b;box-shadow:0 1px 4px #173c2b19;font-weight:600}.inv30-tabs>a>span{font-size:10px;background:#e9ece5;border-radius:10px;min-width:18px;text-align:center;padding:2px 5px}.inv30-filters{display:flex;align-items:center;gap:9px;margin:0;min-width:0}.inv30-filters select,.inv30-filters input{min-height:38px;padding:9px 12px;border:1px solid #E5E7E1;border-radius:8px;font:12px 'Geist',system-ui;background:white;color:#3b5745;min-width:0}.inv30-filters select{max-width:230px}.inv30-filters input{width:230px}.inv30-filter-status{margin:0;padding:0 20px;font-size:12px;color:#64786b;line-height:1.6}.inv30-filter-status:empty{display:none}.inv30-filter-status:not(:empty){padding-bottom:10px}.inv30-table{border-collapse:collapse;width:100%;min-width:850px}.inv30-table th{background:#F8FAF6;color:#6c8072;font-size:10px;font-weight:500;padding:12px 18px;border-bottom:1px solid #E5E7E1;text-align:left}.inv30-table td{font-size:12px;padding:15px 18px;border-bottom:1px solid #edf0e9;vertical-align:middle}.inv30-table th:last-child,.inv30-table td:last-child{text-align:right}.inv30-table tr.is-checked,.inv30-mobile-cards article.is-checked{background:#F4F9F3}.inv30-table tbody tr:hover{background:#F5F8F2}.inv30-asset{display:flex;align-items:center;gap:12px;min-width:170px}.inv30-photo{width:48px;height:48px;display:grid;place-items:center;background:#f0f4ef;border:1px solid #E5E7E1;border-radius:9px;flex:none;overflow:hidden;color:#91a497}.inv30-photo img{width:48px;height:48px;object-fit:cover}.inv30-photo svg{width:20px;height:20px}.inv30-asset strong{display:block;font-size:12px;line-height:1.5;overflow-wrap:anywhere;max-width:290px}.inv30-asset small{display:block;font-size:10px;color:#7b8d80;margin-top:3px}.inv30-identification{font-family:'Geist Mono',ui-monospace,monospace;font-size:11px!important;overflow-wrap:anywhere;min-width:150px}.inv30-identification strong{font-weight:500}.inv30-identification small{display:block;font-family:'Geist Mono',ui-monospace,monospace;font-size:10px;color:#718577;margin-top:5px;line-height:1.5;max-width:240px;overflow-wrap:anywhere}.inv30-location{font-size:11px;display:block;font-weight:500;line-height:1.6;max-width:250px;overflow-wrap:anywhere}.inv30-room{display:block;font-size:10px;line-height:1.6;color:#7b8c7e;max-width:250px;overflow-wrap:anywhere}.inv30-row-actions{display:flex;justify-content:flex-end;align-items:center;gap:6px;white-space:nowrap}.inv30-row-actions .btn{min-height:38px;padding:7px 10px;font-size:11px}.inv30-occurrence{width:38px;padding:7px!important;color:#657d6d!important;justify-content:center}.inv30-empty{padding:40px 20px!important;text-align:center;color:#758878;font-size:13px}.inv30-list-footer{display:flex;align-items:center;justify-content:space-between;gap:18px;flex-wrap:wrap;padding:15px 20px;background:#FAFBF8;font-size:11px;color:#7b8d80;line-height:1.6;border-top:1px solid #E5E7E1}.inv30-list-footer strong{color:#425e4b;font-weight:500}.inv30-pagination{padding:0 20px 16px}.inv30-mobile-cards,.inv30-mobile-qr{display:none}
.inv30-dialog{width:min(550px,92vw);max-height:85dvh;border:1px solid #E5E7E1;border-radius:16px;padding:24px;color:#173c2b;overflow:auto;font-family:'Geist',system-ui}.inv30-dialog::backdrop{background:#0b332580}.inv30-dialog-heading{display:flex;align-items:center;justify-content:space-between;gap:15px;margin-bottom:20px}.inv30-dialog h2{margin:0;font-size:20px}.inv30-dialog h3{font-size:17px;overflow-wrap:anywhere}.inv30-dialog dl{display:grid;gap:7px}.inv30-dialog dt{font-size:12px;color:#718577;margin-top:8px}.inv30-dialog dd{margin:0;font-size:14px;white-space:pre-wrap;overflow-wrap:anywhere}.inv30-dialog-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:24px}.inv30-dialog .op-check{font-size:13px;line-height:1.6;margin:20px 0}.inv30-dialog form>.btn{margin-top:15px}.inv30-dialog [hidden]{display:none!important}
@media(max-width:1200px){.inv30-heading{align-items:flex-start;flex-wrap:wrap}.inv30-progress{grid-template-columns:1fr;gap:20px}.inv30-progress-summary{border-right:0;border-bottom:1px solid #ffffff20;padding:0 0 18px}.inv30-progress-detail dl{margin-bottom:18px}.inv30-toolbar{gap:12px}}
@media(max-width:768px){.inv30-heading{gap:16px}.inv30-title h1{font-size:25px}.inv30-heading-actions{width:100%}.inv30-qr-top{display:none!important}.inv30-progress{padding:20px;gap:18px}.inv30-ring{width:80px;height:80px}.inv30-ring>strong{font-size:20px}.inv30-progress-summary{gap:14px}.inv30-progress-summary h2{font-size:22px}.inv30-progress-detail dl{grid-template-columns:1fr 1fr;gap:16px}.inv30-legend{gap:12px}.inv30-toolbar{padding:14px}.inv30-tabs{width:100%;justify-content:space-between}.inv30-tabs>a{padding:7px 6px;font-size:11px;gap:4px}.inv30-filters{width:100%;flex-wrap:wrap}.inv30-filters select,.inv30-filters input{width:100%;max-width:none;font-size:16px;min-height:42px}.inv30-table-wrap{display:none}.inv30-mobile-cards{display:grid;gap:12px;padding:0 14px 14px}.inv30-mobile-cards article{border:1px solid #E5E7E1;border-radius:13px;padding:16px;background:#fff}.inv30-mobile-cards article>p{font-size:12px;line-height:1.6;margin:12px 0}.inv30-mobile-cards .inv30-asset strong{font-size:14px}.inv30-mobile-cards .inv30-row-actions{margin-top:15px;display:block}.inv30-mobile-cards .inv30-row-actions .btn{display:flex;justify-content:center;width:100%;min-height:42px}.inv30-mobile-cards .inv30-row-actions .inv30-occurrence{display:none}.inv30-list-footer{padding:16px;gap:10px}.inv30-list-footer .btn{width:100%;justify-content:center}.inv30-mobile-qr{display:block;position:fixed;left:14px;right:14px;bottom:calc(82px + env(safe-area-inset-bottom,0px));z-index:35;padding:8px;background:#F4F5F1ed;border-radius:12px;box-shadow:0 0 20px #0b33251a}.inv30-mobile-qr>.btn{display:flex;justify-content:center;width:100%;min-height:46px;font-size:13px}.inventory30-page .shell>main{padding-bottom:calc(175px + env(safe-area-inset-bottom,0px))}.inv30-dialog{padding:20px}.inv30-filter-status{padding-left:14px;padding-right:14px}}



/* Indicadores de gestão */
.ind-nota{margin:16px 0 0;line-height:1.7}.ind-chip{display:inline-block;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600;background:#eef2ef;color:#3f5a4b}.ind-chip.ok{background:#dff0e5;color:#14532d}.ind-chip.warn{background:#fff1d6;color:#7a4d00}.ind-chip.bad{background:#fde3df;color:#8a1c12}.ind-section{margin:34px 0}.ind-section-head{display:flex;gap:16px;align-items:flex-start;margin-bottom:18px;padding-bottom:14px;border-bottom:2px solid #d5e3d9}.ind-section-head>span{flex-shrink:0;width:34px;height:34px;border-radius:50%;background:#0e3b2b;color:#c6f36b;display:flex;align-items:center;justify-content:center;font-weight:700}.ind-section-head h2{margin:0 0 4px;font-size:21px;color:#10372a}.ind-section-head p{margin:0;font-size:14px;color:#3f5a4b;line-height:1.6}.ind-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:16px;align-items:start}.ind-card{background:#fff;border:1px solid #d9e4dc;border-top:5px solid #9fb3a6;border-radius:12px;padding:18px 20px;display:flex;flex-direction:column;gap:11px;min-width:0}
.ind-resumo{margin:0;font-size:13px;line-height:1.55;color:#4f6658}
.ind-exemplo{margin:0;font-size:12.5px;line-height:1.55;color:#2f4a3c;background:#f3f8f1;border-left:3px solid #a0c517;border-radius:6px;padding:8px 11px}
.ind-exemplo b{color:#174c37}
.ind-como{border-top:1px solid #e3ebe5;padding-top:10px}
.ind-como>summary{cursor:pointer;font-size:13px;font-weight:600;color:#174c37;list-style:none}
.ind-como>summary::-webkit-details-marker{display:none}
.ind-como>summary:before{content:"＋ ";color:#5d8f2d}.ind-como[open]>summary:before{content:"－ "}
.ind-como .ind-explain{margin-top:8px}
.ind-card.ind-ok{border-top-color:#1f7a4a}.ind-card.ind-warn{border-top-color:#d99a1c}.ind-card.ind-bad{border-top-color:#c0392b}.ind-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.ind-head h3{margin:0;font-size:17px;color:#10372a}.ind-band{white-space:nowrap;padding:5px 12px;border-radius:20px;font-size:12px;font-weight:700;background:#eef2ef;color:#3f5a4b}.ind-ok .ind-band{background:#dff0e5;color:#14532d}.ind-warn .ind-band{background:#fff1d6;color:#7a4d00}.ind-bad .ind-band{background:#fde3df;color:#8a1c12}.ind-value{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}.ind-value strong{font-size:34px;line-height:1;color:#0e3b2b;letter-spacing:-1px}.ind-value span{font-size:13px;color:#3f5a4b}.ind-meter{height:8px;border-radius:8px;background:#e8eee9;overflow:hidden}.ind-meter span{display:block;height:100%;background:#7f9b89;border-radius:8px}.ind-ok .ind-meter span{background:#1f7a4a}.ind-warn .ind-meter span{background:#d99a1c}.ind-bad .ind-meter span{background:#c0392b}.ind-explain{margin:0;display:grid;gap:0;border-top:1px solid #e3ebe5}.ind-explain>div{display:grid;grid-template-columns:1fr;gap:4px;padding:9px 0;border-bottom:1px solid #edf2ee}.ind-explain dt{font-size:11px;letter-spacing:.8px;text-transform:uppercase;font-weight:700;color:#174c37;padding-top:2px}.ind-explain dd{margin:0;font-size:13px;line-height:1.55;color:#20392d;overflow-wrap:anywhere}.ind-explain code{font:600 13px ui-monospace,Menlo,Consolas,monospace;background:#f1f5f2;color:#10372a;padding:3px 7px;border-radius:5px;white-space:normal}.ind-explain .destaque{background:#f3f8f4;border-radius:8px;padding:11px 12px;border-bottom:0;margin:4px 0}.ind-link{font-size:14px;align-self:flex-start}.ind-bens summary{cursor:pointer;font-size:14px;font-weight:600;color:#174c37}.ind-bens ul{list-style:none;padding:0;margin:10px 0 0;max-height:320px;overflow:auto}.ind-bens li{display:flex;flex-direction:column;gap:3px;padding:9px 0;border-bottom:1px solid #edf2ee;font-size:14px}.ind-bens li a{color:#10372a;font-weight:600}.ind-bens li small{color:#4f6658;font-size:12px}.ind-historico{margin-top:20px;padding:22px 24px}.ind-historico h3{margin:0 0 4px;font-size:17px}@media(max-width:900px){.ind-grid{grid-template-columns:1fr}}@media(max-width:560px){.ind-explain>div{grid-template-columns:1fr;gap:4px}.ind-card{padding:18px}.ind-value strong{font-size:32px}}
/* Equipe de campo */
.campo-painel{margin:18px 0}.campo-painel h2{font-size:18px;margin:0 0 6px}.campo-painel-cab p{font-size:14px;color:#3f5a4b;margin:0 0 14px;line-height:1.6;max-width:900px}.campo-links{list-style:none;padding:0;margin:0 0 14px}.campo-links li{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid #e7ece8}.campo-links li div{display:flex;flex-direction:column;gap:3px;min-width:0}.campo-links small{color:#5f7468;font-size:12px}.campo-links form{margin:0}.campo-form{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1.2fr) minmax(0,.7fr) auto;gap:12px;align-items:end}.campo-achados{margin-top:16px}.campo-achados summary{cursor:pointer;font-weight:600;color:#7a4d00}.campo-achados ul{list-style:none;padding:0}.campo-achados li{padding:10px 0;border-bottom:1px solid #eef2ef;display:flex;flex-direction:column;gap:3px}.campo-achados small{color:#5f7468}.campo-gerado{display:grid;grid-template-columns:240px minmax(0,1fr);gap:28px;align-items:start}.campo-gerado-qr{display:flex;flex-direction:column;gap:8px;align-items:center;text-align:center}.campo-gerado-qr img{border:1px solid #dfe7e1;border-radius:12px;background:#fff}.campo-gerado-qr small{font-size:12px;color:#5f7468}.campo-copiar{display:flex;gap:8px;margin:6px 0 14px}.campo-copiar input{flex:1;min-width:0;font-size:13px}.campo-whats{display:inline-flex}.campo-passos{padding-left:20px;margin:18px 0;line-height:1.7;font-size:14px;color:#20392d}.campo-passos li{margin-bottom:8px}@media(max-width:800px){.campo-form,.campo-gerado{grid-template-columns:1fr}.campo-links li{flex-direction:column;align-items:flex-start}}
/* Relatórios: gráficos limpos */
.r28-column-frame{background:none!important;border-bottom:1px solid #cfdad2!important}.r28-column .r28-column-fill,.r28-column:nth-child(3n) .r28-column-fill,.r28-column:nth-child(3n+2) .r28-column-fill{background:#1f6b4c!important;border-radius:8px 8px 0 0}.r28-column:hover .r28-column-fill{background:#15573f!important;filter:none}.r28-column>span{color:#3f5a4b}.g-ranking{display:flex;flex-direction:column;gap:6px;margin-top:6px}.g-rank-linha{display:flex;flex-direction:column;gap:7px;padding:10px 12px;border-radius:9px;color:#10372a;text-decoration:none}a.g-rank-linha:hover,a.g-rank-linha:focus-visible{background:#f1f6f2}.g-rank-topo{display:flex;justify-content:space-between;align-items:baseline;gap:12px}.g-rank-nome{font-size:13px;min-width:0;overflow-wrap:anywhere}.g-rank-valor{display:flex;align-items:baseline;gap:8px;white-space:nowrap}.g-rank-valor strong{font-size:15px;font-variant-numeric:tabular-nums}.g-rank-valor small{font-size:12px;color:#5f7468;min-width:34px;text-align:right}.analytics-situations .analytics-track span{background:#1f6b4c!important}.g-rank-trilho{height:8px;border-radius:8px;background:#edf2ee;overflow:hidden}.g-rank-trilho span{display:block;height:100%;border-radius:8px;background:#1f6b4c}.g-rank-outros .g-rank-trilho span{background:#a9b9ae}.g-rank-outros{color:#4f6658}.g-destaque{display:flex;align-items:center;gap:16px;margin:8px 0 18px}.g-destaque>strong{font-size:44px;line-height:1;color:#10372a;letter-spacing:-1.5px;font-variant-numeric:tabular-nums}.g-destaque>span{font-size:14px;color:#3f5a4b;line-height:1.5}.g-destaque small{font-size:12px;color:#5f7468}.g-segmentos{display:flex;gap:2px;height:16px;border-radius:9px;overflow:hidden;background:#fff}.g-seg{display:block;min-width:6px;transition:filter .15s}.g-seg:hover,.g-seg:focus-visible{filter:brightness(.88)}.g-lista{display:flex;flex-direction:column;margin-top:16px;border-top:1px solid #edf2ee}.g-item{display:grid;grid-template-columns:12px minmax(0,1fr) auto 44px;align-items:center;gap:12px;padding:11px 4px;border-bottom:1px solid #edf2ee;color:#10372a;text-decoration:none;font-size:13px}.g-item:hover,.g-item:focus-visible{background:#f6f9f7}.g-ponto{width:12px;height:12px;border-radius:4px}.g-item strong{font-size:15px;font-variant-numeric:tabular-nums;text-align:right}.g-item small{font-size:12px;color:#5f7468;text-align:right}
/* Marca: nome sem ícone */
.brand.brand-dourada{padding-left:12px}
.sidebar .brand.brand-dourada strong{font-size:27px!important;line-height:1.08!important;letter-spacing:-.6px!important}.sidebar .brand.brand-dourada small{font-size:10px!important;letter-spacing:.8px!important;margin-top:6px}
.u-convenios{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px;margin:6px 0}.field .u-conv{display:flex!important;flex-direction:row!important;align-items:center;gap:10px;margin:0!important;padding:11px 14px;border:1px solid #d6e2da;border-radius:8px;background:#fff;font-weight:500;cursor:pointer}.field .u-conv:has(input:checked){border-color:#1f6b4c;background:#f1f6f2}.field .u-conv input{width:18px!important;height:18px!important;min-height:0!important;margin:0!important;padding:0!important;flex:0 0 18px;accent-color:#1f6b4c}
.pdf-btns{display:flex;gap:8px;flex-wrap:wrap}
.nav-badge{margin-left:auto;min-width:22px;height:20px;padding:0 6px;border-radius:10px;background:#c9f070;color:#10372a;font-size:11px;font-weight:700;display:inline-flex;align-items:center;justify-content:center}
.sigad-callout{border-left:4px solid #1f6b4c;background:#f1f6f2}.sigad-aviso{color:#8a5a00;font-weight:600}
/* Central de ajuda */
.aj-busca{display:flex;gap:10px;align-items:center;margin:4px 0 18px}.aj-busca input{flex:1;min-height:46px;font-size:15px;padding:10px 14px;border:1px solid #cfdad2;border-radius:10px}
.aj-fluxo{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:6px 0 4px}.aj-fluxo a{display:inline-flex;align-items:center;gap:6px;padding:8px 12px;border-radius:20px;background:#eef5f0;color:#10372a;font-size:12.5px;font-weight:600;text-decoration:none}.aj-fluxo a:hover{background:#dcebe1}.aj-fluxo span.seta{color:#8aa394;font-size:14px}
.aj-grade{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px;margin-top:6px}.aj-card{display:block;padding:16px;border:1px solid #dfe8e2;border-radius:12px;background:#fff;color:#10372a;text-decoration:none}.aj-card:hover{border-color:#1f6b4c;background:#f7fbf8}.aj-card small{display:block;font-size:10.5px;letter-spacing:1px;color:#6c8576;text-transform:uppercase;margin-bottom:6px}.aj-card strong{display:block;font-size:15px;margin-bottom:4px}.aj-card span{font-size:12.5px;color:#4f6658;line-height:1.5}
.aj-topico{border:1px solid #dfe8e2;border-radius:12px;background:#fff;margin-bottom:12px;scroll-margin-top:90px}.aj-topico>summary{list-style:none;cursor:pointer;padding:16px 18px;display:flex;justify-content:space-between;align-items:center;gap:12px}.aj-topico>summary::-webkit-details-marker{display:none}.aj-topico>summary h2{font-size:17px;margin:0}.aj-topico>summary p{margin:4px 0 0;font-size:12.5px;color:#5f7468}.aj-topico>summary:after{content:'+';font-size:22px;color:#1f6b4c}.aj-topico[open]>summary:after{content:'–'}
.aj-corpo{padding:0 18px 18px;border-top:1px solid #edf2ee}.aj-quem{display:inline-block;margin:14px 0 4px;padding:4px 10px;border-radius:6px;background:#f3f6f4;font-size:11.5px;color:#3f5a4b}
.aj-passos{counter-reset:p;list-style:none;padding:0;margin:14px 0}.aj-passos li{counter-increment:p;position:relative;padding:8px 0 8px 42px;font-size:13.5px;line-height:1.6;color:#1d3328}.aj-passos li:before{content:counter(p);position:absolute;left:0;top:7px;width:28px;height:28px;border-radius:50%;background:#1f6b4c;color:#fff;font-weight:700;font-size:13px;display:flex;align-items:center;justify-content:center}
.aj-dicas{margin:6px 0 0;padding:12px 14px;border-radius:10px;background:#fbf8ec;border:1px solid #efe4bd}.aj-dicas strong{display:block;font-size:12.5px;margin-bottom:4px;color:#6b5300}.aj-dicas ul{margin:0;padding-left:18px}.aj-dicas li{font-size:12.5px;line-height:1.6;color:#4a4227}
.aj-ir{display:inline-block;margin-top:12px}.aj-vazio{padding:30px;text-align:center;color:#5f7468}
.aj-faq details{border-bottom:1px solid #edf2ee;padding:12px 2px}.aj-faq summary{cursor:pointer;font-weight:600;font-size:14px;color:#10372a}.aj-faq p{margin:8px 0 0;font-size:13px;line-height:1.6;color:#3f5a4b}
.coord-sigla{display:inline-block;font-weight:700;letter-spacing:.5px;padding:4px 10px;border-radius:6px;background:#e9f2ec;color:#10372a}
/* Termo com vários bens */
.kit-atalho{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:16px 20px;margin:0 0 20px;background:#f3f8f4;border:1px solid #d5e3d9;border-radius:10px}.kit-atalho div{display:flex;flex-direction:column;gap:4px}.kit-atalho strong{font-size:14px;color:#10372a}.kit-atalho span{font-size:13px;color:#3f5a4b}.kit-tabela .kit-check{width:44px;text-align:center}.kit-tabela input[type=checkbox]{width:18px;height:18px;accent-color:#174c37}.kit-contador{font-size:13px;font-weight:600;color:#174c37;margin:10px 0 0}.op-kit-bens{width:100%;border-collapse:collapse;font-size:12px;margin:6px 0 10px}.op-kit-bens th{text-align:left;font-size:10px;color:#54715f;border-bottom:1.5px solid #174c37;padding:7px 6px}.op-kit-bens td{padding:7px 6px;border-bottom:1px solid #e3ebe5;vertical-align:top;overflow-wrap:anywhere}@media(max-width:700px){.kit-atalho{flex-direction:column;align-items:stretch}.op-kit-bens{font-size:11px}}
/* Guia patrimonial: contraste legível */
.enc-relatorio-acoes{display:flex;gap:10px;flex-wrap:wrap}@media(max-width:700px){.enc-relatorio-acoes{width:100%}.enc-relatorio-acoes .btn{flex:1;justify-content:center}}
@media(min-width:1001px){.home19-kpis.home19-kpis-3{grid-template-columns:repeat(3,minmax(0,1fr))}}
.guide-map .guide-node{background:#fff;border:1px solid #cddbd1;color:#10372a;box-shadow:none}.guide-map .guide-node small{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:50%;background:#e4efe7;color:#174c37;font-size:11px;font-weight:700}.guide-map .guide-node strong{color:#10372a;font-size:15px}.guide-map .guide-node span{color:#3f5a4b;font-size:13px}.guide-map .guide-node:hover{border-color:#174c37;background:#f6faf7}.guide-map .guide-node:focus-visible{outline:3px solid #80ad97;outline-offset:2px}.guide-map .guide-node[aria-pressed=true]{background:#0e3b2b;border-color:#0e3b2b;box-shadow:0 4px 12px #0e3b2b26}.guide-map .guide-node[aria-pressed=true] strong{color:#fff}.guide-map .guide-node[aria-pressed=true] span{color:#d4eadb}.guide-map .guide-node[aria-pressed=true] small{background:#c6f36b;color:#0e3b2b}.guide-explanation[hidden]{display:none!important}.guide-explanation h2{color:#10372a}.guide-block{display:grid;grid-template-columns:170px minmax(0,1fr);gap:18px;padding:16px 0;border-top:1px solid #e3ebe5}.guide-block>span,.guide-sources>span{font-size:11px;letter-spacing:1px;text-transform:uppercase;font-weight:700;color:#174c37;padding-top:3px}.guide-block p{margin:0;color:#20392d;font-size:15px;line-height:1.7}.guide-block.pratica{background:#f3f8f4;border-radius:10px;padding:16px;border-top:0;margin:4px 0}.guide-block.exemplo p{color:#20392d}.guide-alert{margin:10px 0 0;padding:12px 16px;border-left:4px solid #c08a1e;background:#fff8e8;color:#5c4108;border-radius:6px;font-size:14px}.guide-sources{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;padding-top:16px;margin-top:12px;border-top:1px solid #e3ebe5}.guide-sources a{color:#1d4ed8;text-decoration:underline;font-size:14px}@media(max-width:700px){.guide-block{grid-template-columns:1fr;gap:6px}}@media(min-width:1180px){.guide-map{grid-template-columns:repeat(5,minmax(0,1fr))}}.guide-hub p{color:#3f5a4b}.guide-hub>span{color:#4f6a5a}
</style>
<link rel="manifest" href="{{ url_for('app_manifest') }}">
<meta name="theme-color" content="#0B3325"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"><meta name="apple-mobile-web-app-title" content="Patrimônio Carajás">
<link rel="apple-touch-icon" href="{{ url_for('app_icon',size=180) }}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;650;700&display=swap" rel="stylesheet" media="(max-width:768px)">
</head>
<body class="{{ 'mobile-dashboard-page' if home_mobile else '' }} {{ 'inventory30-page' if modulo_template=='inv_detalhe' else '' }}">
<svg style="display:none" aria-hidden="true">
<defs>
<symbol id="box" viewBox="0 0 24 24">
<path d="m12 3 9 5v9l-9 5-9-5V8l9-5Zm-9 5 9 5 9-5M12 13v9M7 5.8l9 5"/>
</symbol>
<symbol id="grid" viewBox="0 0 24 24">
<rect x="3" y="3" width="7" height="7" rx="1"/>
<rect x="14" y="3" width="7" height="7" rx="1"/>
<rect x="3" y="14" width="7" height="7" rx="1"/>
<rect x="14" y="14" width="7" height="7" rx="1"/>
</symbol>
<symbol id="list" viewBox="0 0 24 24">
<path d="M8 5h13M8 12h13M8 19h13M3 5h1M3 12h1M3 19h1"/>
</symbol>
<symbol id="check" viewBox="0 0 24 24">
<path d="m6 12 4 4 8-9"/>
<rect x="3" y="3" width="18" height="18" rx="3"/>
</symbol>
<symbol id="move" viewBox="0 0 24 24">
<path d="M3 7h17l-4-4m4 14H3l4 4M20 7l-4 4M3 17l4-4"/>
</symbol>
<symbol id="doc" viewBox="0 0 24 24">
<path d="M14 3H5v18h14V8l-5-5Zm0 0v5h5M8 12h8M8 16h8"/>
</symbol>
<symbol id="chart" viewBox="0 0 24 24">
<path d="M3 21h18M6 17V9M12 17V3M18 17v-5"/>
</symbol>
<symbol id="clock" viewBox="0 0 24 24">
<circle cx="12" cy="12" r="9"/>
<path d="M12 6v6l4 2"/>
</symbol>
<symbol id="leaf" viewBox="0 0 24 24">
<path d="M3 21C1 8 7 2 21 3c1 14-5 20-18 18Zm0 0L17 7M8 16V9m0 7h7"/>
</symbol>
<symbol id="notebook" viewBox="0 0 24 24">
<rect x="4" y="3" width="16" height="12" rx="1"/>
<path d="m4 15-2 5h20l-2-5M9 18h6"/>
</symbol>
<symbol id="scan" viewBox="0 0 24 24"><path d="M8 3H3v5M16 3h5v5M21 16v5h-5M8 21H3v-5"/><rect x="9" y="9" width="6" height="6" rx="1"/></symbol>
<symbol id="camera" viewBox="0 0 24 24">
<rect x="6" y="2" width="12" height="20" rx="3"/>
<circle cx="12" cy="9" r="3"/>
<path d="M9 16h6M9 19h6"/>
</symbol>
<symbol id="drone" viewBox="0 0 24 24">
<rect x="9" y="9" width="6" height="6" rx="1"/>
<path d="m9 9-4-4m10 4 4-4M9 15l-4 4m10-4 4 4"/>
<ellipse cx="5" cy="4" rx="4" ry="2"/>
<ellipse cx="19" cy="4" rx="4" ry="2"/>
<ellipse cx="5" cy="20" rx="4" ry="2"/>
<ellipse cx="19" cy="20" rx="4" ry="2"/>
</symbol>
<symbol id="radio" viewBox="0 0 24 24">
<path d="M8 8V2m8 6V5"/>
<rect x="6" y="8" width="12" height="14" rx="2"/>
<rect x="9" y="11" width="6" height="4" rx="1"/>
<path d="M9 18h6"/>
</symbol>
<symbol id="gps" viewBox="0 0 24 24">
<rect x="6" y="2" width="12" height="20" rx="3"/>
<rect x="9" y="5" width="6" height="8" rx="1"/>
<circle cx="12" cy="17" r="1.5"/>
</symbol>
<symbol id="monitor" viewBox="0 0 24 24">
<rect x="2" y="3" width="20" height="14" rx="2"/>
<path d="M12 17v4M7 21h10"/>
</symbol>
<symbol id="logout" viewBox="0 0 24 24"><path d="M10 4H4v16h6M14 8l4 4-4 4M8 12h12"/></symbol>
</defs>
</svg>
{% macro icon(name) %}<svg aria-hidden="true">
<use href="#{{name}}"/>
</svg>{% endmacro %}
<aside class="sidebar" id="sidebar">
<a class="brand brand-dourada" href="/"><div>
<strong><span>Patrimônio</span><span>Carajás</span></strong>
<small>NGI ICMBio Carajás</small>
</div>
</a>
<nav class="nav" aria-label="Menu principal">
{% for label,ico,endpoint,chave in [('Página inicial','grid','inicio','inicio'),('Bens patrimoniais','box','listar_bens','bens'),('Movimentações','move','movimentacoes','movimentacoes'),('Inventário','check','inventario','inventario'),('Termos e documentos','doc','documentos','documentos'),('Encerramento e baixa','box','encerramento_convenios','baixas'),('Plaquetas','doc','plaquetas_lote','plaquetas'),('Relatórios','chart','relatorios','relatorios')] %}
{% if pode_acessar(endpoint) %}<a href="{{ url_for(endpoint) }}" class="{{ 'active' if (request.endpoint=='plaquetas_lote' and chave=='plaquetas') or (request.endpoint!='plaquetas_lote' and modulo_page and modulo == chave) or (not modulo_page and not cadastros_page and not guia_page and not leitor_page and request.endpoint!='plaquetas_lote' and (((formulario or bem or lista_page) and chave=='bens') or (not formulario and not bem and not lista_page and chave=='inicio'))) else '' }}">{{ icon(ico) }}{{ label }}{% if chave=='bens' and entradas_sigad_pendentes|default(0) %}<span class="nav-badge" title="Compras do SIGAD aguardando tombamento">{{ entradas_sigad_pendentes }}</span>{% endif %}</a>{% endif %}{% endfor %}
<a href="{{ url_for('guia_patrimonial') }}" class="{{ 'active' if guia_page }}">{{icon('doc')}}Guia patrimonial</a>
<a href="{{ url_for('central_ajuda') }}" class="{{ 'active' if modulo_page and modulo == 'ajuda' }}">{{icon('doc')}}Central de ajuda</a>
{% if usuario.perfil in ("Administrador", "Operador") %}<span class="nav-section-label">CONFIGURAÇÃO</span><details class="nav-group" {{ 'open' if cadastros_page }}>
<summary class="{{ 'active' if cadastros_page else '' }}">{{icon('list')}}<span>Cadastros</span><svg class="nav-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="m8 10 4 4 4-4"/></svg></summary>
<div class="nav-submenu"><a href="{{ url_for('cadastros') }}" class="{{ 'selected' if cadastro_tipo == 'locais' }}">Locais</a><a href="{{ url_for('convenios_cadastro') }}" class="{{ 'selected' if cadastro_tipo == 'convenios' }}">Convênios</a><a href="{{ url_for('categorias_cadastro') }}" class="{{ 'selected' if cadastro_tipo == 'categorias' }}">Categorias</a><a href="{{ url_for('coordenacoes_cadastro') }}" class="{{ 'selected' if cadastro_tipo == 'coordenacoes' }}">Coordenações</a>{% if usuario.perfil == 'Administrador' %}<a href="{{ url_for('usuarios_cadastro') }}" class="{{ 'selected' if cadastro_tipo == 'usuarios' }}">Usuários</a>{% endif %}</div>
</details>{% endif %}

<form class="sidebar-logout" method="post" action="{{ url_for('logout') }}">
<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
<button class="logout-button" type="submit">{{icon('logout')}}<span>Sair</span></button>
</form></nav>
<div class="sideart">{{icon('leaf')}}</div>
<div class="sidefoot">Gestão patrimonial de projetos<br>NGI ICMBio Carajás<br>Versão 1.0</div>
</aside>
<button class="menu-overlay" id="menu-overlay" aria-label="Fechar menu" tabindex="-1" hidden>
</button>
<div class="shell">
<header class="top">
<button class="btn mobile" id="menu" aria-label="Abrir menu" aria-expanded="false">{{icon('list')}}</button>
<span class="crumb">Patrimônio &nbsp; / &nbsp; {{modulo_titulo if modulo_page else 'Cadastros / ' ~ cadastro_titulo if cadastros_page else 'Cadastro do bem' if formulario else 'Ficha do bem' if bem else 'Guia patrimonial' if guia_page else 'Ler QR Code' if leitor_page else 'Bens patrimoniais' if lista_page else 'Página inicial'}}</span>
<form class="global-search" method="get" action="{{ url_for('listar_bens') }}" role="search"><label class="visually-hidden" for="global-q">Buscar no patrimônio</label><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/></svg><input id="global-q" type="search" name="q" placeholder="Buscar no patrimônio…" maxlength="120" aria-label="Buscar no patrimônio"></form>
<div class="profile">
<span class="avatar">{{ iniciais }}</span>
<div>{{ usuario.nome }}<small>{{ usuario.perfil }}</small>
</div>
</div>

</header>
<main>

{% for mensagem in get_flashed_messages() %}<div class="feedback" role="status">{{ mensagem }}</div>{% endfor %}
{% if modulo_page %}
{% include modulo_template %}
{% elif guia_page %}
{% include "guia" %}
{% elif cadastros_page and cadastro_tipo == 'categorias' %}
{% include 'categorias_cadastro' %}
{% elif cadastros_page and cadastro_tipo == 'coordenacoes' %}
{% include 'coordenacoes_cadastro' %}
{% elif cadastros_page and cadastro_tipo == 'convenios' %}
{% include "convenios_cadastro" %}
{% elif cadastros_page and cadastro_tipo == 'usuarios' %}
{% include "usuarios_cadastro" %}
{% elif cadastros_page %}
{% include "cadastros" %}
{% elif formulario %}
{% include "formulario" %}
{% elif bem %}
{% include "ficha_compacta" %}
{% elif leitor_page %}
{% include "leitor_qr" %}
{% elif lista_page %}
{% include "lista_bens" %}
{% else %}
{% include "visao_geral" %}
{% endif %}<footer>
<span>Patrimônio Carajás · NGI ICMBio Carajás</span>
<span>Gestão patrimonial de projetos · versão 1.0</span>
</footer>
</main>
</div>
<dialog id="home-camera" class="mh-camera"><div class="mh-camera-heading"><h2>Ler QR Code</h2><button type="button" class="btn" id="home-camera-close">Fechar</button></div><video id="home-camera-video" playsinline muted></video><p id="home-camera-status" role="status">Aponte para o QR Code da plaqueta.</p><form id="home-camera-manual"><label for="home-camera-code">Ou digite a plaqueta / série</label><div><input id="home-camera-code" maxlength="500" required><button type="submit" class="mh-primary">Localizar</button></div></form></dialog>
<script>
(()=>{
const dialog=document.getElementById('home-camera'),video=document.getElementById('home-camera-video'),message=document.getElementById('home-camera-status');let stream=null,timer=null,running=false,serial=0,mode='general',busy=false,decoderPromise;
const fieldURL={{ url_for('inventario_campo')|tojson }},fieldInventory={{ inv.id|tojson if inv is defined and inv else campanha_atual.id|tojson if campanha_atual else 'null' }},fieldLocal={{ campo_local_filtro|default(local_filtro|default(''))|tojson }},canConfer={{ (not usuario.leitura)|tojson }},assetURL={{ url_for('listar_bens')|tojson }},publicOrigin=new URL({{ PUBLIC_URL_MOBILE|tojson }}).origin;
function stop(){running=false;serial++;clearTimeout(timer);if(stream)stream.getTracks().forEach(t=>t.stop());stream=null;video.srcObject=null;busy=false;}
function finish(raw){const code=raw.trim();if(!code)return;stop();if(canConfer&&(mode==='inventory'||window.matchMedia('(max-width:768px)').matches)){const url=new URL(fieldURL,location.origin);url.searchParams.set('codigo',code);if(fieldInventory)url.searchParams.set('inventario_id',fieldInventory);const selected=document.getElementById('campo-local')||document.getElementById('inv30-local');if(selected||fieldLocal)url.searchParams.set('local',selected?selected.value:fieldLocal);location.assign(url.pathname+url.search);return;}try{const u=new URL(code,location.origin);if([location.origin,publicOrigin].includes(u.origin)&&/^\/bem\/\d+\/?$/.test(u.pathname)){location.assign(u.pathname);return;}}catch(e){}location.assign(assetURL+'?q='+encodeURIComponent(code.slice(0,120)));}
function loadDecoder(){if(window.jsQR)return Promise.resolve(window.jsQR);if(!decoderPromise)decoderPromise=new Promise((resolve,reject)=>{const tag=document.createElement('script');tag.src='/static/vendor/jsQR.js';tag.onload=()=>window.jsQR?resolve(window.jsQR):reject(new Error('Leitor indisponível. Digite a plaqueta abaixo.'));tag.onerror=()=>{decoderPromise=null;reject(new Error('Não foi possível carregar o leitor. Digite a plaqueta abaixo.'));};document.head.append(tag);});return decoderPromise;}
async function start(nextMode){if(busy)return;stop();mode=nextMode;busy=true;const turn=serial;dialog.showModal();message.textContent='Abrindo a câmera…';try{if(!window.isSecureContext)throw new Error('A câmera exige HTTPS. Abra o endereço seguro do sistema.');if(!navigator.mediaDevices?.getUserMedia)throw new Error('Câmera não disponível. Digite a plaqueta abaixo.');let detector=null,decode=null;if(window.BarcodeDetector){try{if((await BarcodeDetector.getSupportedFormats()).includes('qr_code'))detector=new BarcodeDetector({formats:['qr_code']});}catch(e){}}if(!detector)decode=await loadDecoder();if(turn!==serial||!dialog.open)return;const obtained=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'}},audio:false});if(turn!==serial||!dialog.open){obtained.getTracks().forEach(t=>t.stop());return;}stream=obtained;video.srcObject=stream;await video.play();if(turn!==serial||!dialog.open){stop();return;}running=true;message.textContent='Aponte para o QR Code da plaqueta.';const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d',{willReadFrequently:true});async function tick(){if(!running||turn!==serial)return;try{let result;if(detector){const codes=await detector.detect(video);result=codes.find(x=>x.rawValue)?.rawValue;}else if(video.readyState>=2){canvas.width=Math.min(video.videoWidth||640,640);canvas.height=Math.round(canvas.width*(video.videoHeight||480)/(video.videoWidth||640));ctx.drawImage(video,0,0,canvas.width,canvas.height);const frame=ctx.getImageData(0,0,canvas.width,canvas.height);result=decode(frame.data,canvas.width,canvas.height,{inversionAttempts:'dontInvert'})?.data;}if(result&&turn===serial&&dialog.open){finish(result);return;}}catch(e){}if(running&&turn===serial)timer=setTimeout(tick,250);}tick();}catch(e){if(turn!==serial)return;stop();message.textContent=e.name==='NotAllowedError'?'Permissão de câmera negada. Libere a câmera ou digite a plaqueta abaixo.':e.name==='NotFoundError'?'Nenhuma câmera encontrada. Digite a plaqueta abaixo.':e.message||'Não foi possível abrir a câmera.';}finally{if(turn===serial)busy=false;}}
document.querySelectorAll('[data-home-camera]').forEach(b=>b.addEventListener('click',()=>start(b.dataset.homeCamera)));
document.addEventListener('click',e=>{if(e.target.closest('#mobile-nav-qr')){e.preventDefault();start('general');}else if(e.target.closest('[data-inventory-scan]')){e.preventDefault();start('inventory');}});
document.getElementById('home-camera-close').addEventListener('click',()=>dialog.close());dialog.addEventListener('close',stop);dialog.addEventListener('cancel',stop);window.addEventListener('pagehide',stop);document.addEventListener('visibilitychange',()=>{if(document.hidden){stop();if(dialog.open)dialog.close();}});document.getElementById('home-camera-manual').addEventListener('submit',e=>{e.preventDefault();finish(document.getElementById('home-camera-code').value);});
})();
</script>
<nav class="mobile-bottom-nav" aria-label="Navegação no celular"><a href="{{ url_for('inicio') }}" class="{{ 'current' if request.endpoint=='inicio' }}" {{ 'aria-current=page' if request.endpoint=='inicio' }}>{{ icon('grid') }}<span>Visão geral</span></a><a href="{{ url_for('listar_bens') }}" class="{{ 'current' if request.endpoint=='listar_bens' }}">{{ icon('box') }}<span>Bens</span></a><a id="mobile-nav-qr" class="mobile-nav-qr" href="{{ url_for('leitor_qr',camera=1) }}" aria-label="Ler QR Code"><span>{{ icon('scan') }}</span></a>{% if pode_acessar("inventario") %}<a href="{{ url_for('inventario') }}" class="{{ 'current' if request.endpoint in ['inventario','inventario_detalhe','conferir_inventario'] }}">{{ icon('check') }}<span>Inventário</span></a>{% else %}<a href="{{ url_for('guia_patrimonial') }}">{{ icon('doc') }}<span>Guia</span></a>{% endif %}<button type="button" data-mobile-menu aria-controls="sidebar" aria-expanded="false">{{ icon('list') }}<span>Menu</span></button></nav>
<script>
const menu = document.querySelector('#menu');
const sidebar = document.querySelector('#sidebar');
const overlay = document.querySelector('#menu-overlay');
const mobileMedia = window.matchMedia('(max-width:768px)');
let menuInvoker=menu;

function setMenu(open,invoker) {
    if(invoker)menuInvoker=invoker;
    document.querySelectorAll('[data-mobile-menu]').forEach(b=>b.setAttribute('aria-expanded',String(open)));
    sidebar.classList.toggle('open', open);
    overlay.classList.toggle('open', open);
    overlay.hidden = !open;
    menu.setAttribute('aria-expanded', String(open));
    menu.setAttribute('aria-label', open ? 'Fechar menu' : 'Abrir menu');
    sidebar.inert = mobileMedia.matches && !open;
}
menu.addEventListener('click', () => setMenu(!sidebar.classList.contains('open'),menu));
document.querySelectorAll('[data-mobile-menu]').forEach(b=>b.addEventListener('click',()=>{setMenu(!sidebar.classList.contains('open'),b);if(sidebar.classList.contains('open'))sidebar.querySelector('.nav a')?.focus();}));
overlay.addEventListener('click', () => {
    setMenu(false);
    menuInvoker.focus()
});
document.addEventListener('keydown', e => {
    if(e.key==='Tab'&&mobileMedia.matches&&sidebar.classList.contains('open')){const nodes=[...sidebar.querySelectorAll('a[href],button,summary')].filter(n=>n.getClientRects().length);const first=nodes[0],last=nodes[nodes.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}
    if (e.key === 'Escape' && sidebar.classList.contains('open')) {
        setMenu(false);
        menuInvoker.focus()
    }
});
document.querySelectorAll('.nav a').forEach(a => a.addEventListener('click', () => setMenu(false)));
mobileMedia.addEventListener('change', () => setMenu(false));
setMenu(false);
if('serviceWorker' in navigator&&window.isSecureContext)navigator.serviceWorker.register({{ url_for('app_service_worker')|tojson }}).catch(()=>{});
</script>
</body>
</html>"""


# ============================================================
# 5. TELA DE LOGIN
# ============================================================
LOGIN_TEMPLATE = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Entrar · Patrimônio Carajás</title>
<link rel="preload" as="image" href="{{ url_for('static', filename='identidade-visual/login-rio-hd.jpg') }}" fetchpriority="high">
<style>
* { box-sizing: border-box; }
body { margin:0; background:#f5f8f2; color:#1c2922; font:14px system-ui,-apple-system,'Segoe UI',sans-serif; }
.login-shell { display:grid; grid-template-columns:1fr 1fr; min-height:100dvh; }
.identity { background:#004622; color:#e5eee6; padding:60px; display:flex; flex-direction:column; justify-content:space-between; }
.brand { font-size:25px; font-weight:650; letter-spacing:-.7px; }
.brand small { display:block; font-size:10px; letter-spacing:2px; margin-top:10px; font-weight:400; }
h1 { font-size:clamp(30px,3.8vw,56px); max-width:560px; line-height:1.12; font-weight:600; letter-spacing:-1.8px; margin:30px 0; }
.identity p { max-width:430px; line-height:1.8; color:#b4cbbd; }
.identity footer { font-size:11px; color:#a1baa9; margin-top:35px; }
.formarea { display:flex; align-items:center; justify-content:center; padding:40px; }
.formbox { width:100%; max-width:370px; }
.eyebrow { color:#52705d; font-size:10px; letter-spacing:1.8px; text-transform:uppercase; }
h2 { margin:15px 0 10px; font-size:29px; letter-spacing:-1px; }
.formbox p { color:#758177; line-height:1.7; font-size:13px; }
form { margin-top:30px; }
label { display:block; margin:20px 0 8px; font-size:12px; font-weight:600; }
input { width:100%; padding:13px; min-height:46px; border:1px solid #dce4d9; border-radius:6px; background:white; color:#1c2922; font:inherit; }
input:focus-visible, button:focus-visible { outline:3px solid #87b399; outline-offset:2px; }
button { width:100%; min-height:46px; margin-top:24px; background:#004622; color:white; border:0; border-radius:6px; font:600 13px system-ui,sans-serif; cursor:pointer; }
button:hover { background:#20533e; }
.error { background:#fff0e9; color:#8a3929; border:1px solid #efd9cf; padding:12px; border-radius:6px; font-size:12px; line-height:1.6; margin-top:18px; }
.info { padding-top:18px; margin-top:24px; border-top:1px solid #e1e6dd; font-size:11px!important; }
@media(max-width:760px) { .login-shell{grid-template-columns:1fr}.identity{padding:28px}.identity h1{font-size:29px;margin:24px 0 12px}.identity p{margin:0;font-size:12px}.identity footer{display:none}.brand{font-size:22px}.formarea{padding:32px 24px}.formbox{max-width:420px}input{font-size:16px} }
.identity .brand small{color:#d1e4b6}.identity{border-top:5px solid #a0c517}.login-card button:focus-visible{outline:3px solid #598727;outline-offset:3px}

:root {
  --verde-menu:     #0B3325;
  --verde-escuro:   #0E3B2B;
  --verde-logo:     #14513A;
  --verde:          #15573F;
  --verde-medio:    #6FCF97;
  --verde-limao:    #C7F26B;
  --verde-claro:    #E1F0E6;
  --fundo:          #F4F5F1;
}
body{background:var(--fundo)}.identity{background:var(--verde-menu);border-top-color:var(--verde-limao)}button{background:var(--verde-escuro)}button:hover{background:var(--verde)}input:focus-visible,button:focus-visible{outline-color:var(--verde)}
.system-name{font-weight:600;font-size:16px;line-height:1.6;max-width:520px}

/* Identidade institucional no acesso; artes originais, sem alterar proporções. */
.identity{justify-content:flex-start;padding:clamp(30px,3vw,60px)}.identity>.brand{flex:0 0 auto}.identity>.login-story{margin:auto 0;padding:42px 0}.identity .login-story h1{margin:0 0 28px}.identity .login-story p{margin-top:14px}
.formarea{flex-direction:column;padding:24px clamp(22px,2.5vw,48px) 22px;gap:18px;min-width:0}.login-content{display:flex;flex:1 0 auto;align-items:center;justify-content:center;width:100%;padding:12px 0}.formbox{max-width:390px}.login-icmbio{display:block;width:96px;height:auto;max-width:100%;object-fit:contain;margin:0 0 20px}.formbox h2{color:var(--verde);font-size:30px;font-weight:650;line-height:1.25;margin-top:12px}.formbox form{margin-top:24px}.formbox input,.formbox button{min-height:48px}.formbox .info{font-size:12px!important;margin:16px 0 0;padding-top:16px;color:#637268}
.login-units{flex:0 0 auto;width:100%;max-width:920px;margin:0;padding:12px;background:transparent;border:0;border-radius:0;box-sizing:border-box}.login-units-desktop{display:block;width:100%;height:auto;object-fit:contain}.login-units-mobile{display:none}
@media(max-width:1100px) and (min-width:761px){.login-shell{grid-template-columns:.85fr 1.15fr}.identity .login-story h1{font-size:clamp(30px,3.4vw,44px)}.formarea{padding:24px}.login-icmbio{width:84px}}
@media(min-width:761px) and (max-height:850px){.formarea{padding:18px 28px;gap:12px}.login-content{padding:0}.login-icmbio{width:72px;margin-bottom:12px}.formbox h2{font-size:28px;margin:10px 0 8px}.formbox form{margin-top:18px}.formbox label{margin:13px 0 7px}.formbox button{margin-top:18px}.formbox .info{margin-top:12px;padding-top:12px}.login-units{padding:10px}.login-units-desktop{max-height:145px;object-fit:contain}}
@media(max-width:760px){.identity{padding:24px}.identity>.login-story{margin:0;padding:24px 0 0}.identity .login-story h1{font-size:28px;margin:0 0 14px;line-height:1.2}.identity .login-story p{font-size:12px;margin:8px 0 0}.identity .system-name{font-size:14px}.formarea{padding:28px 22px 24px;gap:28px}.login-content{padding:0}.login-icmbio{width:88px;margin-bottom:20px}.formbox h2{font-size:28px}.formbox input{font-size:16px}.login-units{padding:10px;max-width:520px}.login-units-desktop{display:none}.login-units-mobile{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.login-units-mobile svg{width:100%;height:112px;display:block;min-width:0}}

/* Tela de entrada com fotografia da floresta */
.identity.identity-foto{position:relative;background-color:#0B3325;background-size:cover;background-position:center 38%;background-repeat:no-repeat;border-top:0;justify-content:space-between;color:#fff}
.identity-foto .brand{color:#fff;font-size:27px;font-weight:700;letter-spacing:-.6px;text-shadow:0 1px 12px rgba(0,0,0,.35)}.identity-foto .brand small{color:#e6efd9;letter-spacing:2.4px}
.identity-foto>.login-story{margin:auto 0 0;padding:0 0 56px}.identity-foto .login-story h1{color:#fff;font-size:clamp(32px,3.6vw,54px);line-height:1.1;letter-spacing:-1.6px;max-width:560px;margin:0 0 22px;text-shadow:0 2px 18px rgba(0,0,0,.35)}
.story-linha{display:block;width:64px;height:4px;border-radius:2px;background:#C7F26B;margin:0 0 18px}
.identity-foto .system-name{color:#f1f5ee;font-size:12px;font-weight:600;letter-spacing:1.6px;text-transform:uppercase;margin:0}
.foto-credito{position:absolute;right:clamp(20px,2.5vw,40px);bottom:20px;margin:0;font-size:11px;color:rgba(255,255,255,.82);letter-spacing:.3px;text-shadow:0 1px 6px rgba(0,0,0,.5)}
@media(max-width:760px){.identity.identity-foto{min-height:300px;padding:22px 22px 44px;background-position:center 30%}.identity-foto>.login-story{padding:0}.identity-foto .login-story h1{font-size:26px;margin:0 0 12px}.story-linha{width:48px;margin-bottom:12px}.identity-foto .system-name{font-size:10.5px}.foto-credito{bottom:14px;right:16px;font-size:10px}}

/* Cabeçalho do formulário centralizado */
.login-icmbio{margin-left:auto!important;margin-right:auto!important}
.formbox h2{text-align:center;margin-bottom:4px}
.formbox>p{text-align:center}

/* modelo com a foto do rio: foto ocupa ~60% da tela, título mais leve, crédito à esquerda */
@media(min-width:1101px){.login-shell{grid-template-columns:1.5fr 1fr}}
@media(min-width:761px){.identity.identity-foto{background-position:center 55%}.identity-foto .login-story h1{font-size:clamp(30px,3vw,48px);letter-spacing:-1.2px;max-width:520px}.foto-credito{left:clamp(30px,3vw,60px);right:auto}}
</style>
<link rel="manifest" href="{{ url_for('app_manifest') }}">
<meta name="theme-color" content="#0B3325"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"><meta name="apple-mobile-web-app-title" content="Patrimônio Carajás">
<link rel="apple-touch-icon" href="{{ url_for('app_icon',size=180) }}">
</head>
<body>
<div class="login-shell">
<section class="identity identity-foto" style="background-image:linear-gradient(180deg,rgba(6,28,19,.55) 0%,rgba(6,28,19,.05) 26%,rgba(6,28,19,.10) 52%,rgba(6,28,19,.82) 100%),url('{{ url_for('static', filename='identidade-visual/login-rio-hd.jpg') }}')">
<div class="brand">Patrimônio Carajás<small>NGI ICMBio Carajás</small></div>
<div class="login-story"><h1>Gestão que cuida do patrimônio e da conservação.</h1><span class="story-linha" aria-hidden="true"></span>
<p class="system-name">Sistema de Gestão Patrimonial dos Projetos</p></div>
<p class="foto-credito">Foto: João Marcos Rosa</p>

</section>
<main class="formarea"><div class="login-content"><div class="formbox">
<img class="login-icmbio" src="{{ url_for('identidade_visual',nome='icmbio') }}" alt="ICMBio — Instituto Chico Mendes de Conservação da Biodiversidade" width="966" height="1080">
<h2>Bem-vindo de volta.</h2>
{% for mensagem in get_flashed_messages() %}<div role="status" style="padding:12px;background:#E1F0E6;color:#15573F;border-radius:8px">{{ mensagem }}</div>{% endfor %}
{% if erro %}<div class="error" role="alert">{{ erro }}</div>{% endif %}
<form method="post" action="{{ url_for('login',next=request.args.get('next','/')) }}">
<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
<label for="email">E-mail</label>
<input id="email" name="email" type="email" maxlength="254" autocomplete="username" value="{{ email }}" required>
<label for="senha">Senha</label>
<input id="senha" name="senha" type="password" maxlength="512" autocomplete="current-password" required>
<button type="submit">Entrar no sistema</button>
</form>
<p><a href="{{ url_for('esqueci_senha') }}" style="color:#15573F;text-decoration:underline;display:inline-flex;align-items:center;min-height:48px">Esqueci minha senha</a></p>
<p class="info">Acesso restrito a usuários cadastrados.</p>
</div></div><figure class="login-units" aria-label="Unidades de conservação do NGI ICMBio Carajás"><img class="login-units-desktop" src="{{ url_for('identidade_visual',nome='unidades') }}" alt="Parque Nacional dos Campos Ferruginosos; Floresta Nacional de Carajás; Floresta Nacional do Tapirapé-Aquiri; APA do Igarapé Gelado; Floresta Nacional do Itacaiúnas; Reserva Biológica do Tapirapé" width="2048" height="451"><div class="login-units-mobile"><svg viewBox="0 0 466 451" role="img" aria-label="Parque Nacional dos Campos Ferruginosos" preserveAspectRatio="xMidYMid meet"><title>Parque Nacional dos Campos Ferruginosos</title><defs><clipPath id="login-unidade-0"><rect x="0" y="0" width="466" height="451"/></clipPath></defs><image href="{{ url_for('identidade_visual',nome='unidades') }}" width="2048" height="451" clip-path="url(#login-unidade-0)"/></svg><svg viewBox="466 0 269 451" role="img" aria-label="Floresta Nacional de Carajás" preserveAspectRatio="xMidYMid meet"><title>Floresta Nacional de Carajás</title><defs><clipPath id="login-unidade-1"><rect x="466" y="0" width="269" height="451"/></clipPath></defs><image href="{{ url_for('identidade_visual',nome='unidades') }}" width="2048" height="451" clip-path="url(#login-unidade-1)"/></svg><svg viewBox="735 0 287 451" role="img" aria-label="Floresta Nacional do Tapirapé-Aquiri" preserveAspectRatio="xMidYMid meet"><title>Floresta Nacional do Tapirapé-Aquiri</title><defs><clipPath id="login-unidade-2"><rect x="735" y="0" width="287" height="451"/></clipPath></defs><image href="{{ url_for('identidade_visual',nome='unidades') }}" width="2048" height="451" clip-path="url(#login-unidade-2)"/></svg><svg viewBox="1022 0 350 451" role="img" aria-label="Área de Proteção Ambiental do Igarapé Gelado" preserveAspectRatio="xMidYMid meet"><title>Área de Proteção Ambiental do Igarapé Gelado</title><defs><clipPath id="login-unidade-3"><rect x="1022" y="0" width="350" height="451"/></clipPath></defs><image href="{{ url_for('identidade_visual',nome='unidades') }}" width="2048" height="451" clip-path="url(#login-unidade-3)"/></svg><svg viewBox="1372 0 350 451" role="img" aria-label="Floresta Nacional do Itacaiúnas" preserveAspectRatio="xMidYMid meet"><title>Floresta Nacional do Itacaiúnas</title><defs><clipPath id="login-unidade-4"><rect x="1372" y="0" width="350" height="451"/></clipPath></defs><image href="{{ url_for('identidade_visual',nome='unidades') }}" width="2048" height="451" clip-path="url(#login-unidade-4)"/></svg><svg viewBox="1722 0 326 451" role="img" aria-label="Reserva Biológica do Tapirapé" preserveAspectRatio="xMidYMid meet"><title>Reserva Biológica do Tapirapé</title><defs><clipPath id="login-unidade-5"><rect x="1722" y="0" width="326" height="451"/></clipPath></defs><image href="{{ url_for('identidade_visual',nome='unidades') }}" width="2048" height="451" clip-path="url(#login-unidade-5)"/></svg></div></figure></main>
</div>
</body></html>"""


# ============================================================
# 6. COMANDOS DE PREPARAÇÃO — executar apenas no banco novo
# ============================================================
@app.cli.command("iniciar-banco")
def iniciar_banco():
    """Cria as tabelas ausentes. Não apaga nem altera tabelas existentes."""
    try:
        if db.engine.dialect.name == "postgresql":
            with db.engine.begin() as conn:
                conn.execute(text("CREATE SCHEMA IF NOT EXISTS patrimonio"))
        db.create_all()
        if db.engine.dialect.name == "postgresql":
            with db.engine.begin() as conn:
                # O schema não será publicado pela Data API.
                conn.execute(
                    text(
                        "REVOKE ALL ON SCHEMA patrimonio FROM PUBLIC, anon, authenticated"
                    )
                )
                conn.execute(
                    text(
                        "REVOKE ALL ON ALL TABLES IN SCHEMA patrimonio FROM anon, authenticated"
                    )
                )
                for tabela in ("usuarios", "tentativas_login"):
                    conn.execute(
                        text(
                            f"ALTER TABLE patrimonio.{tabela} ENABLE ROW LEVEL SECURITY"
                        )
                    )
        click.echo("Banco do patrimônio preparado. Nenhum bem fictício foi importado.")
    except SQLAlchemyError as erro:
        db.session.rollback()
        app.logger.error("Preparação do banco: %s", type(erro).__name__)
        raise click.ClickException(
            "Não foi possível preparar o banco. Confira DATABASE_URL e a senha no Render."
        ) from None


@app.cli.command("criar-admin")
@click.option("--email", prompt="E-mail do administrador")
@click.option("--nome", prompt="Nome completo")
@click.option(
    "--senha",
    prompt="Senha do administrador",
    hide_input=True,
    confirmation_prompt="Repita a senha",
)
def criar_admin(email, nome, senha):
    """Cria administrador pelo terminal. Nunca usa uma senha padrão."""
    email = email.strip().casefold()
    nome = nome.strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254:
        raise click.ClickException("Informe um e-mail válido.")
    if not 2 <= len(nome) <= 120:
        raise click.ClickException("O nome deve ter de 2 a 120 caracteres.")
    if not 12 <= len(senha) <= 128:
        raise click.ClickException("A senha deve ter entre 12 e 128 caracteres.")
    try:
        if db.session.scalar(select(Usuario).where(Usuario.email == email)):
            raise click.ClickException(
                "Esse usuário já existe. A senha existente não foi alterada."
            )
        db.session.add(
            Usuario(nome=nome, email=email, senha_hash=generate_password_hash(senha))
        )
        db.session.commit()
        click.echo("Administrador criado. Você já pode entrar no sistema.")
    except SQLAlchemyError as erro:
        db.session.rollback()
        app.logger.error("Criação de administrador: %s", type(erro).__name__)
        raise click.ClickException(
            "Falha ao criar usuário. Execute iniciar-banco e confira a conexão."
        ) from None


@app.cli.command("verificar-banco")
def verificar_banco():
    """Verifica a conexão sem exibir senha ou endereço do banco."""
    try:
        db.session.execute(text("SELECT 1"))
        quantidade = db.session.scalar(select(func.count()).select_from(Usuario))
        click.echo(f"Conexão OK. Usuários cadastrados: {quantidade}.")
    except SQLAlchemyError:
        db.session.rollback()
        raise click.ClickException(
            "A conexão ou as tabelas ainda não estão prontas."
        ) from None


# ============================================================
# 7. SESSÃO, AUTORIZAÇÃO E PROTEÇÕES DOS FORMULÁRIOS
# ============================================================
@app.before_request
def carregar_usuario():
    g.usuario = None
    if request.endpoint in {"health", "prontidao"}:
        return
    if session.get("usuario_id"):
        usuario = db.session.get(Usuario, session["usuario_id"])
        if (
            usuario
            and usuario.ativo
            and usuario.versao_sessao == session.get("versao_sessao")
        ):
            g.usuario = usuario
        else:
            session.clear()


def login_obrigatorio(funcao):
    @wraps(funcao)
    def protegida(*args, **kwargs):
        if g.usuario is None:
            return redirect(url_for("login",next=request.full_path if request.query_string else request.path))
        return funcao(*args, **kwargs)

    return protegida


@app.before_request
def controlar_perfil():
    if not g.usuario:
        return None
    if g.usuario.perfil not in PERFIS:
        abort(403)
    if request.endpoint and request.endpoint not in ENDPOINTS_PUBLICOS and not pode_acessar(request.endpoint):
        abort(403)
    gravacao = request.method not in {"GET", "HEAD", "OPTIONS"} and request.endpoint not in {"login", "logout", "esqueci_senha", "redefinir_senha", "aceite_termo", "campo_enviar"}
    formulario_edicao = request.endpoint in {"cadastrar_bem", "editar_bem", "editar_base", "editar_convenio", "editar_categoria", "editar_coordenacao"}
    if g.usuario.leitura and (gravacao or formulario_edicao):
        abort(403)


@app.errorhandler(403)
def acesso_negado(erro):
    return render_template_string(
        "<!doctype html><html lang='pt-BR'><meta charset='utf-8'><title>Acesso restrito</title>"
        "<body style='font:16px system-ui;padding:40px;color:#194432'><h1>Acesso restrito</h1>"
        "<p>Seu perfil não permite esta ação.</p><a href='/'>Voltar ao início</a></body></html>"
    ), 403


CSP = "; ".join((
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: blob:",
    "media-src 'self' blob:",
    "connect-src 'self'",
    "worker-src 'self'",
    "manifest-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
))


# arquivos que não mudam (foto e logos da tela de login, ícones): o navegador pode guardar
ENDPOINTS_ARQUIVOS_FIXOS = {"static", "identidade_visual", "app_icon"}


@app.after_request
def proteger_resposta(resposta):
    # imagens e arquivos fixos (pasta static) podem ficar guardados no navegador por 7 dias:
    # assim a foto da tela de login não é baixada de novo a cada saída. Páginas continuam sem cache.
    if request.endpoint in ENDPOINTS_ARQUIVOS_FIXOS and resposta.status_code in (200, 304):
        resposta.headers["Cache-Control"] = "public, max-age=604800"
    else:
        resposta.headers["Cache-Control"] = "no-store"
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    resposta.headers["X-Frame-Options"] = "DENY"
    # HTTPS: Flask-WTF exige a origem de referência. Envie só a origem, sem expor o token da URL.
    resposta.headers["Referrer-Policy"] = "strict-origin" if request.endpoint in {"esqueci_senha","redefinir_senha","aceite_termo","campo_coleta","campo_enviar"} else "same-origin"
    if request.endpoint in {"esqueci_senha","redefinir_senha","aceite_termo","campo_coleta"}:
        resposta.headers["X-Robots-Tag"] = "noindex, nofollow"
    resposta.headers["Permissions-Policy"] = "geolocation=(), microphone=()"
    if request.endpoint == "campo_sw":
        resposta.headers["Service-Worker-Allowed"] = "/campo/"
    # CSP: só recursos do próprio sistema, além das fontes do Google Fonts.
    resposta.headers["Content-Security-Policy"] = CSP
    return resposta


@app.errorhandler(CSRFError)
def csrf_expirado(erro):
    return (
        render_template_string(
            LOGIN_TEMPLATE,
            erro="Formulário expirado. Atualize a página e tente novamente.",
            email="",
        ),
        400,
    )


@app.errorhandler(SQLAlchemyError)
def banco_indisponivel(erro):
    db.session.rollback()
    app.logger.error("Banco indisponível: %s", type(erro).__name__)
    comunicar_falha(erro)
    return (
        render_template_string(
            LOGIN_TEMPLATE,
            erro="Banco temporariamente indisponível ou não inicializado. Tente novamente após a preparação.",
            email="",
        ),
        503,
    )


# ============================================================
# 8. LOGIN E SAÍDA
# ============================================================
def digest(valor):
    return hmac.new(app.secret_key.encode(), valor.encode(), hashlib.sha256).hexdigest()


@app.route("/login", methods=["GET", "POST"])
def login():
    destino=request.args.get('next','/')
    if not destino.startswith('/') or destino.startswith('//') or chr(92) in destino or any(ord(c)<32 for c in destino):destino='/'
    if g.usuario:
        return redirect(destino)
    erro = None
    email = ""
    status = 200
    if request.method == "POST":
        email = request.form.get("email", "").strip().casefold()[:254]
        senha = request.form.get("senha", "")[:512]
        agora = int(time.time())
        ip_hash = digest(request.remote_addr or "desconhecido")
        email_hash = digest(email)
        if db.engine.dialect.name == "postgresql":
            # Serializa tentativas do mesmo IP entre os workers.
            lock_id = int(ip_hash[:16], 16) - (1 << 63)
            db.session.execute(
                text("SELECT pg_advisory_xact_lock(:chave)"), {"chave": lock_id}
            )
        recentes = TentativaLogin.instante >= agora - 900
        por_ip = db.session.scalar(
            select(func.count())
            .select_from(TentativaLogin)
            .where(recentes, TentativaLogin.ip_hash == ip_hash)
        )
        por_email = db.session.scalar(
            select(func.count())
            .select_from(TentativaLogin)
            .where(recentes, TentativaLogin.email_hash == email_hash)
        )
        if por_ip >= 25 or por_email >= 8:
            db.session.rollback()
            erro = "Muitas tentativas. Aguarde 15 minutos e tente novamente."
            status = 429
        else:
            usuario = db.session.scalar(select(Usuario).where(Usuario.email == email))
            senha_valida = check_password_hash(
                usuario.senha_hash if usuario else HASH_FICTICIO, senha
            )
            db.session.execute(
                delete(TentativaLogin).where(TentativaLogin.instante < agora - 86400)
            )
            if usuario and usuario.ativo and senha_valida:
                # As falhas recentes continuam contadas até expirar a janela.
                db.session.commit()
                session.clear()
                session.permanent = True
                session["usuario_id"] = usuario.id
                session["versao_sessao"] = usuario.versao_sessao
                return redirect(destino)
            db.session.add(
                TentativaLogin(ip_hash=ip_hash, email_hash=email_hash, instante=agora)
            )
            db.session.commit()
            erro = "E-mail ou senha inválidos."
            status = 401
    return render_template_string(LOGIN_TEMPLATE, erro=erro, email=email), status


@app.post("/logout")
@login_obrigatorio
def logout():
    session.clear()
    return redirect(url_for("login"))


# ============================================================
# 9. PAINEL E FICHA — registros reais do patrimônio
# ============================================================
@app.template_filter("brl")
def brl(valor):
    if valor is None:
        return "Não informado"
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def convenios_do_gestor():
    """None para quem vê tudo; conjunto de convênios para o Gestor de convênio."""
    usuario = getattr(g, 'usuario', None)
    if not usuario or usuario.perfil != 'Gestor de convênio':
        return None
    if not hasattr(g, 'convenios_gestor'):
        g.convenios_gestor = set(db.session.scalars(
            select(GestorConvenio.convenio_id).where(GestorConvenio.usuario_id == usuario.id)))
    return g.convenios_gestor


def escopo_bem():
    ids = convenios_do_gestor()
    return true() if ids is None else Bem.convenio_id.in_(sorted(ids) or [-1])


def bem_visivel(bem):
    ids = convenios_do_gestor()
    return ids is None or bem.convenio_id in ids


def convenio_visivel(convenio_id):
    ids = convenios_do_gestor()
    return ids is None or convenio_id in ids


def contexto_usuario():
    iniciais = "".join(parte[0] for parte in g.usuario.nome.split()[:2]).upper()
    ids = convenios_do_gestor()
    nomes = db.session.scalars(select(Convenio.nome).where(Convenio.id.in_(sorted(ids) or [-1])).order_by(Convenio.nome)).all() if ids is not None else []
    pendentes = 0
    if not g.usuario.leitura:
        pendentes = db.session.scalar(select(func.count(EntradaSigad.id)).where(EntradaSigad.status == 'Aguardando tombamento')) or 0
    return {"usuario": g.usuario, "iniciais": iniciais, "convenios_gestor_nomes": nomes, "entradas_sigad_pendentes": pendentes}


def contexto_painel():
    # SQL aggregates; never materialize all the asset records for dashboard or forms.
    dados = db.session.execute(select(
        func.count(Bem.id),
        func.coalesce(func.sum(Bem.valor), 0),
        func.coalesce(func.sum(case((Bem.valor.is_(None), 1), else_=0)), 0),
        func.coalesce(func.sum(case((Bem.conferido.is_(True), 1), else_=0)), 0),
    ).where(Bem.encerrado.is_(False), escopo_bem())).one()
    quantidade, total, pendentes, conferidos = dados
    return dict(
        quantidade=quantidade, total=total, valores_pendentes=pendentes,
        conferidos=conferidos, percentual=round(conferidos / quantidade * 100) if quantidade else 0,
        convenios=db.session.scalars(select(Bem.convenio).where(escopo_bem()).distinct().order_by(Bem.convenio)).all(),
        locais=db.session.scalars(select(Bem.local).where(escopo_bem()).distinct().order_by(Bem.local)).all(),
        **contexto_usuario(),
    )


@app.get("/")
@login_obrigatorio
def inicio():
    por_convenio = db.session.execute(
        select(Bem.convenio, func.count(Bem.id))
        .where(Bem.encerrado.is_(False), escopo_bem())
        .group_by(Bem.convenio)
        .order_by(func.count(Bem.id).desc(), Bem.convenio)
        .limit(8)
    ).all()
    hoje = hoje_local()
    atrasados = (
        db.session.scalar(
            select(func.count())
            .select_from(Movimento)
            .where(
                Movimento.status == 'Concluída',
                Movimento.tipo.in_(('Entrega temporária', 'Manutenção')),
                Movimento.devolvido_em.is_(None),
                Movimento.previsao_retorno < hoje,
            )
        )
        or 0
    )
    vencendo = (
        db.session.scalar(
            select(func.count())
            .select_from(Convenio)
            .where(
                Convenio.ativo.is_(True),
                Convenio.fim >= hoje,
                Convenio.fim <= hoje + timedelta(days=90),
            )
        )
        or 0
    )
    pendentes = (
        db.session.scalar(
            select(func.count()).select_from(Movimento).where(Movimento.status == 'Pendente')
        )
        or 0
    )
    analise = (
        db.session.scalar(
            select(func.count())
            .select_from(ProcessoBaixa)
            .where(ProcessoBaixa.status == 'Em análise')
        )
        or 0
    )
    campanha = db.session.scalar(
        select(CampanhaInventario)
        .where(CampanhaInventario.status == 'Aberto')
        .order_by(CampanhaInventario.id.desc())
        .limit(1)
    )
    recentes = db.session.scalars(select(Movimento).order_by(Movimento.id.desc()).limit(7)).all()
    dados = contexto_painel()
    local = request.args.get('local', '').strip()[:160]
    busca = request.args.get('q', '').strip()[:120]
    categoria = inteiro(request.args.get('categoria_id'))
    consulta = select(Bem).where(Bem.encerrado.is_(False), escopo_bem())
    if local:
        consulta = consulta.where(Bem.local == local)
    if categoria:
        consulta = consulta.where(Bem.categoria_id == categoria)
    if busca:
        consulta = consulta.where(
            or_(
                *(
                    c.icontains(busca, autoescape=True)
                    for c in (
                        Bem.nome,
                        Bem.serie,
                        Bem.numero_ngi,
                        Bem.plaqueta_original,
                        Bem.responsavel,
                    )
                )
            )
        )
    grupos = db.session.execute(
        select(Bem.local, func.count(Bem.id))
        .where(Bem.encerrado.is_(False))
        .group_by(Bem.local)
        .order_by(func.count(Bem.id).desc(), Bem.local)
        .limit(4)
    ).all()
    # Até quatro linhas: três locais e o restante consolidado quando necessário.
    outros = dados['quantidade'] - sum(n for _, n in grupos[:3])
    locais_grafico = [
        dict(nome=nome or 'Local não informado', n=n, local=nome) for nome, n in grupos[:3]
    ]
    if outros and len(grupos) > 3:
        locais_grafico.append(dict(nome='Outros locais', n=outros, local=None))
    elif len(grupos) > 3:
        locais_grafico.append(dict(nome=grupos[3][0], n=grupos[3][1], local=grupos[3][0]))
    return render_template_string(
        TEMPLATE,
        bem=None,
        formulario=False,
        por_convenio=por_convenio,
        maior_grupo=max((x['n'] for x in locais_grafico), default=1),
        locais_grafico=locais_grafico,
        atrasados=atrasados,
        convenios_vencendo=vencendo,
        pendentes_mov=pendentes,
        baixas_analise=analise,
        campanha_atual=campanha,
        recentes=recentes,
        home_local=local,
        home_busca=busca,
        home_categoria=categoria,
        home_mobile=not g.usuario.leitura,
        PUBLIC_URL_MOBILE=PUBLIC_URL,
        saudacao_mobile=(
            'Bom dia'
            if datetime.now(timezone(timedelta(hours=-3))).hour < 12
            else (
                'Boa tarde'
                if datetime.now(timezone(timedelta(hours=-3))).hour < 18
                else 'Boa noite'
            )
        ),
        categorias_home=db.session.scalars(select(Categoria).order_by(Categoria.nome)).all(),
        **paginar_operacao(consulta.order_by(Bem.id.desc())),
        **dados
    )


@app.get("/bens")
@login_obrigatorio
def listar_bens():
    q = request.args.get("q", "").strip()[:120]
    convenio = request.args.get("convenio", "").strip()[:160]
    local = request.args.get("local", "").strip()[:160]
    situacao = request.args.get("situacao", "").strip()[:30]
    ordenacao = request.args.get("ordem", "recentes")
    ordens = {
        "recentes": (Bem.id.desc(),),
        "nome": (Bem.nome.asc(), Bem.id.asc()),
        "local": (Bem.local.asc(), Bem.nome.asc(), Bem.id.asc()),
        "valor": (Bem.valor.desc().nullslast(), Bem.id.desc()),
    }
    if ordenacao not in ordens:
        ordenacao = "recentes"
    acervo = request.args.get("acervo", "ativos")
    if acervo not in {"ativos", "baixados", "todos"}:
        acervo = "ativos"
    categoria_filtro=inteiro(request.args.get("categoria_id"))
    filtros = [escopo_bem()]
    if categoria_filtro:filtros.append(Bem.categoria_id==categoria_filtro)
    if acervo != "todos":
        filtros.append(Bem.encerrado.is_(acervo == "baixados"))
    if q:
        campos = (Bem.nome, Bem.descricao, Bem.serie, Bem.numero_ngi,
                  Bem.plaqueta_original, Bem.origem, Bem.marca, Bem.modelo, Bem.responsavel, Bem.categoria,
                  Bem.nota_fiscal, Bem.fornecedor, Bem.coordenacao, Bem.ingresso_detalhe)
        filtros.append(or_(*(campo.icontains(q, autoescape=True) for campo in campos)))
    if convenio:
        filtros.append(Bem.convenio == convenio)
    if local:
        filtros.append(Bem.local == local)
    if situacao:
        filtros.append(Bem.situacao == situacao)
    classif = request.args.get("classificacao", "")
    if classif not in CLASSIFICACOES:
        classif = ""
    if classif:
        filtros.append(Bem.classificacao == classif)
    ingresso = request.args.get("ingresso", "")
    if ingresso not in FORMAS_INGRESSO:
        ingresso = ""
    if ingresso:
        filtros.append(Bem.forma_ingresso == ingresso)
    nota = request.args.get("nota", "")
    if nota not in {"com", "sem"}:
        nota = ""
    anexada = select(NotaFiscalBem.bem_id).where(NotaFiscalBem.bem_id == Bem.id).exists()
    if nota == "com":
        filtros.append(or_(Bem.nota_fiscal != "", anexada))
    elif nota == "sem":
        filtros.extend((Bem.nota_fiscal == "", ~anexada))
    total_filtrado = db.session.scalar(select(func.count(Bem.id)).where(*filtros)) or 0
    por_pagina = 25
    paginas = max(1, (total_filtrado + por_pagina - 1) // por_pagina)
    try:
        pagina = max(1, min(int(request.args.get("pagina", "1")), paginas))
    except (TypeError, ValueError):
        pagina = 1
    bens = db.session.scalars(select(Bem).where(*filtros)
        .order_by(*ordens[ordenacao]).limit(por_pagina).offset((pagina - 1) * por_pagina)).all()
    try:
        destaque = int(request.args.get("destacar", "0"))
    except (TypeError, ValueError):
        destaque = 0
    def url_pagina(numero):
        return url_for("listar_bens", pagina=numero, q=q, convenio=convenio,
                       local=local, situacao=situacao, ordem=ordenacao, acervo=acervo, categoria_id=categoria_filtro, nota=nota or None, classificacao=classif or None)
    # Short page window with first/last links, even with thousands of assets.
    numeros = sorted({1, paginas, *range(max(1, pagina - 2), min(paginas, pagina + 2) + 1)})
    return render_template_string(
        TEMPLATE, bem=None, formulario=False, lista_page=True,
        bens=bens, q=q, acervo=acervo, categoria_selecionada=categoria_filtro,
        categorias_filtro=db.session.scalars(select(Categoria).order_by(Categoria.nome)).all(), filtro_convenio=convenio, filtro_local=local,
        filtro_situacao=situacao, filtro_nota=nota, filtro_classif=classif, classificacoes=CLASSIFICACOES, filtro_ingresso=ingresso, formas_ingresso=FORMAS_INGRESSO, ordenacao=ordenacao, situacoes=SITUACOES,
        total_filtrado=total_filtrado, pagina=pagina, paginas=paginas,
        primeiro=(pagina - 1) * por_pagina + 1 if total_filtrado else 0,
        ultimo=min(pagina * por_pagina, total_filtrado),
        numeros_paginas=numeros, url_pagina=url_pagina, destaque=destaque,
        **contexto_painel(),
    )


@app.get("/health")
def health():
    # Verifica somente o processo. A conexão é conferida pelo comando verificar-banco.
    return {"status": "ok", "versao": "1.0"}



# ============================================================
# 10. CADASTRO REAL, FOTO E IDENTIFICAÇÃO PATRIMONIAL
# ============================================================
FORMULARIO_BEM = r"""
<div class="single-heading"><div><a class="back" href="{{ url_for('ficha', bem_id=registro.id) if registro else url_for('listar_bens') }}">← Bens patrimoniais</a><h1>{{ 'Editar bem' if registro else 'Cadastrar bem' }}</h1><p>Todos os dados em uma única página. Preencha e salve.</p></div><small>Campos obrigatórios *</small></div>
<nav class="registry-navigation" aria-label="Navegação dos bens"><a href="{{ url_for('listar_bens') }}" >Bens cadastrados</a>{% if not usuario.leitura %}<a href="{{ request.path }}" class="current" aria-current="page">{{ 'Editar cadastro' if registro else 'Cadastrar bem' }}</a>{% endif %}</nav>
{% if erros %}<div class="erros" role="alert"><strong>Confira os campos antes de salvar:</strong><ul>{% for erro in erros %}<li>{{ erro }}</li>{% endfor %}</ul></div>{% endif %}
<form method="post" enctype="multipart/form-data" id="bem-form" novalidate>
<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
<input type="hidden" name="operacao_token" value="{{ operacao_token }}">
<input type="hidden" name="revisao" value="{{ valores.get('revisao', registro.revisao if registro else 0) }}">
{% if not registro and valores.get('entrada_sigad_id') %}<input type="hidden" name="entrada_sigad_id" value="{{ valores.get('entrada_sigad_id') }}"><input type="hidden" name="entrada_sigad_texto" value="{{ valores.get('entrada_sigad_texto','') }}"><div class="callout sigad-callout"><strong>Tombamento de compra do SIGAD</strong><p>{{ valores.get('entrada_sigad_texto','') }}. Os dados da compra já vieram preenchidos. Confira com o bem em mãos e complete número de série, plaqueta, local e foto.</p></div>{% endif %}
{% if registro %}<div class="callout"><strong>Alterações de localização e responsabilidade</strong><p>Use <a href="{{ url_for('movimentacoes',aba='cadastro',bem_id=registro.id) }}">Nova movimentação</a> para registrar mudança de local, sala ou responsável e gerar o termo de entrega.</p></div>{% endif %}
<div class="single-layout"><div class="single-main"><section class="form-section"><h2>Identificação do bem</h2><p>Informe as características que identificam o patrimônio.</p>
<div class="fields">
<div class="field wide"><label for="nome">Nome do bem *</label><input id="nome" name="nome" maxlength="160" required value="{{ valores.get('nome','') }}" placeholder="Ex.: Notebook Dell Latitude 3450"></div>
<div class="field wide"><label for="categoria_id">Categoria do bem{{ ' *' if not registro }}</label><select id="categoria_id" name="categoria_id" {{ 'required' if not registro }}><option value="">{{ 'Sem categoria · registro anterior' if registro and not registro.categoria_id else 'Selecione a categoria' }}</option>{% for c in categorias_cadastradas %}<option value="{{ c.id }}" {{ 'selected' if valores.get('categoria_id','')|string==c.id|string }}>{{ c.nome }}{{ ' · Inativa' if not c.ativo else '' }}</option>{% endfor %}</select><small>Use Cadastros → Categorias para criar classificações como móveis, eletrodomésticos ou veículos.</small></div>
<div class="field wide"><label for="coordenacao_id">Coordenação responsável</label><select id="coordenacao_id" name="coordenacao_id"><option value="">{{ 'Selecione a coordenação' if coordenacoes_cadastradas else 'Nenhuma coordenação cadastrada' }}</option>{% for c in coordenacoes_cadastradas %}<option value="{{ c.id }}" {{ 'selected' if valores.get('coordenacao_id','')|string==c.id|string }}>{{ c.sigla }} — {{ c.nome }}{{ ' · Inativa' if not c.ativo else '' }}</option>{% endfor %}</select><small>Opcional. A lista vem de Cadastros → Coordenações.</small></div>
<div class="field wide"><label for="descricao">Descrição do bem *</label><textarea id="descricao" name="descricao" maxlength="5000" required placeholder="Características que permitem identificar este bem">{{ valores.get('descricao','') }}</textarea></div>
{% for key,label,limite in [('marca','Marca',100),('modelo','Modelo',120)] %}<div class="field"><label for="{{ key }}">{{ label }} *</label><input id="{{ key }}" name="{{ key }}" maxlength="{{ limite }}" required value="{{ valores.get(key,'') }}"></div>{% endfor %}
<div class="field"><label for="serie_excecao">Número de série *</label><select id="serie_excecao" name="serie_excecao">{% for s in ['Informado','Não possui','Ilegível'] %}<option {{ 'selected' if valores.get('serie_excecao','Informado') == s }}>{{ s }}</option>{% endfor %}</select></div>
<div class="field" id="serie-area"><label for="serie">Informe o número de série *</label><input id="serie" name="serie" maxlength="160" value="{{ valores.get('serie','') }}"><small>Transcreva o identificador do fabricante. Letras são normalizadas para maiúsculas.</small></div>
<div class="field wide" id="justificativa-serie-area"><label for="serie_justificativa">Justificativa da ausência / ilegibilidade *</label><textarea id="serie_justificativa" name="serie_justificativa" maxlength="2000">{{ valores.get('serie_justificativa','') }}</textarea></div>
</div><div class="single-divider"><h3>Plaqueta patrimonial</h3>{% if registro and registro.numero_ngi %}<div class="callout"><strong>{{ registro.numero_ngi }}</strong><p>Número de patrimônio definido. Não pode ser alterado pelo cadastro.{% if registro.plaqueta_original %} Plaqueta antiga: {{ registro.plaqueta_original }}.{% endif %}</p></div><input type="hidden" name="possui_plaqueta" value="nao">
{% else %}<div class="field"><label for="possui_plaqueta">O bem já possui plaqueta? *</label><select name="possui_plaqueta" id="possui_plaqueta"><option value="nao" {{ 'selected' if valores.get('possui_plaqueta','nao') == 'nao' }}>Não possui</option><option value="sim" {{ 'selected' if valores.get('possui_plaqueta') == 'sim' }}>Sim, possui plaqueta (inventários anteriores)</option></select></div>
<div class="fields" id="plaqueta-area" style="margin-top:20px">
<div class="field"><label for="plaqueta_original">Número da plaqueta original *</label><input id="plaqueta_original" name="plaqueta_original" maxlength="120" value="{{ valores.get('plaqueta_original','') }}"></div>
<div class="field"><label for="origem">Origem da plaqueta *</label><input id="origem" name="origem" maxlength="120" list="origens-plaqueta" placeholder="Ex.: Inventário 2023" value="{{ valores.get('origem','') }}"><datalist id="origens-plaqueta"><option value="Inventário 2023"><option value="ICMBio"></datalist><small>Clique no campo para escolher "Inventário 2023" ou digite outra origem.</small></div></div>
<small class="hint">Com plaqueta antiga, o número de patrimônio sai dela (PA 010 vira 0010). Sem plaqueta? Salve o bem primeiro: a ficha terá o botão para gerar o próximo número da sequência.</small>{% endif %}
<div class="field" style="margin-top:16px"><label for="etiqueta_situacao">Situação da etiqueta física</label><select id="etiqueta_situacao" name="etiqueta_situacao">{% for st in ['Não verificada','Sem etiqueta','Danificada','Legível'] %}<option {{ 'selected' if valores.get('etiqueta_situacao','Não verificada')==st }}>{{ st }}</option>{% endfor %}</select><small>Permite listar etiquetas ausentes e reimprimir o número existente.</small></div></div></section><section class="form-section"><h2>Aquisição e condição do bem</h2><p>Informe de quem é o bem e como ele foi adquirido.</p><div class="fields">
{% set forma_ing = valores.get('forma_ingresso','Compra') or 'Compra' %}<div class="field"><label for="forma_ingresso">Forma de entrada *</label><select id="forma_ingresso" name="forma_ingresso">{% for f in formas_ingresso %}<option value="{{ f }}" {{ 'selected' if forma_ing==f }}>{{ f }}</option>{% endfor %}</select><small>Como o bem chegou ao NGI.</small></div>
<div class="field" id="ingresso-area" {{ 'hidden' if forma_ing=='Compra' }}><label for="ingresso_detalhe" id="ingresso-rotulo">{{ 'Quem doou? *' if forma_ing=='Doação' else 'Processo de destinação (SEI) ou auto de infração' }}</label><input id="ingresso_detalhe" name="ingresso_detalhe" maxlength="200" value="{{ valores.get('ingresso_detalhe','') }}" placeholder="{{ 'Ex.: Vale S.A.' if forma_ing=='Doação' else 'Ex.: 02123.000456/2025-11' }}"></div>
<script>(()=>{const f=document.getElementById('forma_ingresso'),a=document.getElementById('ingresso-area'),r=document.getElementById('ingresso-rotulo'),i=document.getElementById('ingresso_detalhe');if(!f)return;
function att(){const v=f.value;a.hidden=v==='Compra';if(v==='Doação'){r.textContent='Quem doou? *';i.placeholder='Ex.: Vale S.A.';}else{r.textContent='Processo de destinação (SEI) ou auto de infração';i.placeholder='Ex.: 02123.000456/2025-11';}}f.addEventListener('change',att);att();})();</script>
{% set e_uniao = valores.get('origem_recurso')=='uniao' or (convenio_uniao_id and valores.get('convenio_id','')|string == convenio_uniao_id|string) %}<div class="field wide"><label for="origem_recurso">De quem é o bem? *</label><select id="origem_recurso" name="origem_recurso"><option value="convenio" {{ 'selected' if not e_uniao }}>Vinculado a um convênio / projeto</option><option value="uniao" {{ 'selected' if e_uniao }}>ICMBio · Patrimônio da União (sem convênio)</option></select><small>Bens próprios do ICMBio não precisam de convênio.</small></div>
<div class="field wide" id="convenio-area" {{ 'hidden' if e_uniao }}><label for="convenio_id">Convênio / projeto *</label><select id="convenio_id" name="convenio_id" {{ '' if e_uniao else 'required' }}><option value="">Selecione o convênio</option>{% for c in convenios_cadastrados %}<option value="{{ c.id }}" {{ 'selected' if valores.get('convenio_id','')|string == c.id|string }}>{{ c.nome }}{{ ' · Inativo' if not c.ativo else '' }}</option>{% endfor %}</select><small>{% if registro and not registro.convenio_id %}Valor anterior: {{ registro.convenio }}. Selecione o cadastro correspondente. {% endif %}<a href="{{ url_for('convenios_cadastro') }}" target="_blank" rel="noopener">Cadastrar convênio em outra aba</a> · Atualize esta página antes de iniciar o preenchimento para carregar novos convênios.</small></div>
<script>(()=>{const o=document.getElementById('origem_recurso'),a=document.getElementById('convenio-area'),s=document.getElementById('convenio_id');if(!o)return;
function att(){const u=o.value==='uniao';a.hidden=u;s.required=!u;}o.addEventListener('change',att);att();})();</script>
<div class="field"><label for="data_aquisicao">Data de aquisição</label><input type="date" id="data_aquisicao" name="data_aquisicao" max="{{ hoje }}" value="{{ valores.get('data_aquisicao','') }}"></div>
<div class="field"><label for="valor">Valor de aquisição (R$)</label><input id="valor" name="valor" inputmode="decimal" placeholder="Ex.: 6.800,00" value="{{ valores.get('valor','') }}"><small>Informe centavos com vírgula. Zero é permitido para aquisição sem custo.</small></div>
<div class="field wide classif-box"><label for="classificacao">Este item é patrimônio? *</label><select id="classificacao" name="classificacao" required><option value="">Escolha: Sim ou Não</option>{% for c in classificacoes %}<option value="{{ c }}" {{ 'selected' if valores.get('classificacao','')==c }}>{{ 'Sim · Patrimônio (bem permanente)' if c=='Patrimônio' else 'Não · Controle simples (não é patrimônio)' }}</option>{% endfor %}</select><small id="classif-dica">Regra do NGI ICMBio Carajás: item permanente com valor <strong>igual ou superior a R$ 250,00</strong> é patrimônio e recebe plaqueta. Abaixo disso, fica só em controle simples.</small></div>
<div class="field wide" id="classif-just-area" hidden><label for="classificacao_justificativa">Por que a classificação é diferente da regra? *</label><textarea id="classificacao_justificativa" name="classificacao_justificativa" maxlength="2000" placeholder="Ex.: equipamento de campo de R$ 150 que precisa de controle individual e termo de responsabilidade.">{{ valores.get('classificacao_justificativa','') }}</textarea></div>
<script>(()=>{const v=document.getElementById('valor'),c=document.getElementById('classificacao'),d=document.getElementById('classif-dica'),a=document.getElementById('classif-just-area'),limite=250;
function num(){let t=(v.value||'').trim().replace(/^R\$\s*/i,'').replace(/\s/g,'');if(!t)return null;if(/^\d{1,3}(\.\d{3})+$/.test(t))t=t.replace(/\./g,'');const n=Number(t.includes(',')?t.replace(/\./g,'').replace(',','.'):t);return isFinite(n)?n:null;}
function att(){const n=num(),sug=n!==null&&n<limite?'Não é patrimônio':'Patrimônio',esc=c.value;
d.innerHTML=n===null?'Regra do NGI ICMBio Carajás: item permanente com valor <strong>igual ou superior a R$ 250,00</strong> é patrimônio e recebe plaqueta. Abaixo disso, fica só em controle simples.':(sug==='Patrimônio'?'Valor de R$ '+n.toLocaleString('pt-BR',{minimumFractionDigits:2})+': pela regra, <strong>é patrimônio</strong> (escolha Sim).':'Valor de R$ '+n.toLocaleString('pt-BR',{minimumFractionDigits:2})+': pela regra, <strong>não é patrimônio</strong> (abaixo de R$ 250,00 · escolha Não).');
a.hidden=!esc||esc===sug;}
v.addEventListener('input',att);c.addEventListener('change',att);att();})();</script>
<div class="field"><label for="nota_fiscal">Nº da nota fiscal</label><input id="nota_fiscal" name="nota_fiscal" maxlength="60" placeholder="Opcional" value="{{ valores.get('nota_fiscal','') }}"></div>
<div class="field"><label for="fornecedor">Fornecedor</label><input id="fornecedor" name="fornecedor" maxlength="160" placeholder="Opcional" value="{{ valores.get('fornecedor','') }}"></div>
<div class="field wide"><label for="nota_fiscal_arquivo">{{ 'Substituir arquivo da nota fiscal' if registro and registro.nota_fiscal_anexada else 'Anexar nota fiscal (PDF ou foto)' }}</label><input type="file" id="nota_fiscal_arquivo" name="nota_fiscal_arquivo" accept="application/pdf,.pdf,image/jpeg,image/png,image/webp,image/heic,image/heif,image/avif,.heic,.heif,.avif"><small>Opcional: bens antigos podem ficar sem nota. PDF ou imagem, até 5 MB.{% if registro and registro.nota_fiscal_anexada %} Arquivo atual: <a href="{{ url_for('nota_fiscal_bem', bem_id=registro.id) }}" target="_blank" rel="noopener">abrir nota fiscal</a>.{% endif %}</small></div>
<div class="field wide"><label for="aquisicao_justificativa">Justificativa se data ou valor não estiver disponível</label><textarea id="aquisicao_justificativa" name="aquisicao_justificativa" maxlength="2000">{{ valores.get('aquisicao_justificativa','') }}</textarea></div>
</div><div class="single-divider"><div class="fields">
{% for key,label,opcoes in [('situacao','Situação de uso',situacoes),('conservacao','Estado de conservação',conservacoes)] %}<div class="field"><label for="{{ key }}">{{ label }} *</label><select id="{{ key }}" name="{{ key }}" required>{% for opcao in opcoes %}<option {{ 'selected' if valores.get(key) == opcao }}>{{ opcao }}</option>{% endfor %}</select></div>{% endfor %}
<div class="field wide"><label for="observacoes">Observações</label><textarea id="observacoes" name="observacoes" maxlength="5000">{{ valores.get('observacoes','') }}</textarea></div>
</div></div></section><section class="form-section"><div class="section-top"><div><h2>Localização e responsável</h2><p>Escolha uma base cadastrada. O endereço e as coordenadas vêm do cadastro do local.</p></div><button type="button" class="text-action" id="abrir-base">+ Nova base</button></div>
<div class="fields">
<div class="field wide"><label for="base_id">Base / escritório / local *</label><select id="base_id" name="base_id" required><option value="">Selecione o local do bem</option>{% for base in bases %}<option value="{{ base.id }}" {{ 'selected' if valores.get('base_id','')|string == base.id|string }}>{{ base.nome }}{{ ' · Inativa' if not base.ativo else '' }}</option>{% endfor %}</select>
{% if registro and not registro.base_id %}<small>Local do cadastro anterior: {{ registro.local }}. Selecione a base correspondente para vincular este bem.</small>{% endif %}
<noscript><a href="{{ url_for('cadastros') }}">Cadastrar uma base em Cadastros</a></noscript></div>
<div id="base-detalhes" class="base-details wide" hidden><span class="base-tag">Local cadastrado</span><strong id="base-endereco"></strong><span id="base-coordenadas"></span><a id="base-mapa" target="_blank" rel="noopener noreferrer">Abrir no mapa ↗</a></div>
<div class="field wide"><label for="complemento">Sala, setor ou complemento do bem</label><input id="complemento" name="complemento" maxlength="200" value="{{ valores.get('complemento','') }}" placeholder="Ex.: Sala administrativa · Estação 02"></div>
<div class="field"><label for="responsavel">Responsável pelo bem *</label><input id="responsavel" name="responsavel" list="responsaveis-opcoes" maxlength="160" required value="{{ valores.get('responsavel','') }}"><datalist id="responsaveis-opcoes">{% for r in responsaveis %}<option value="{{ r }}">{% endfor %}</datalist></div>
<div class="field"><label for="responsavel_contato">E-mail ou contato</label><input id="responsavel_contato" name="responsavel_contato" maxlength="160" value="{{ valores.get('responsavel_contato','') }}"></div>
</div></section></div><aside class="single-aside"><section class="form-section"><h2>Foto do bem</h2><p>Uma imagem facilita a identificação.</p>
<div class="photo-box">{% if registro and registro.tem_foto %}<img class="photo-preview" src="{{ url_for('foto_bem', bem_id=registro.id) }}" alt="Foto atual"><label class="checkline"><input type="checkbox" name="remover_foto" value="sim"> Remover foto atual</label>{% endif %}
</div><div class="field" style="margin-top:16px"><label for="foto">{{ 'Substituir foto' if registro and registro.tem_foto else 'Anexar foto' }}</label><input type="file" id="foto" name="foto" accept="image/jpeg,image/png,image/webp,image/heic,image/heif,image/avif,.heic,.heif,.avif"><small>No celular, você pode escolher uma foto ou usar a câmera, conforme as opções do aparelho. JPEG, PNG, WebP, HEIC/HEIF ou AVIF, até 10 MB. A imagem é otimizada e os metadados são removidos. A prévia HEIC pode não aparecer neste navegador; o servidor faz a conversão.</small></div>
<img id="preview" class="photo-preview" hidden alt="Prévia da foto selecionada"><div class="photo-tip">A foto será salva junto com o cadastro.</div>
</section><section class="form-section summary-box"><span class="eyebrow">RESUMO DO BEM</span><h3 id="resumo-nome">Novo bem</h3><dl><dt>Localização</dt><dd id="resumo-local">Selecione uma base</dd><dt>Plaqueta</dt><dd id="resumo-plaqueta">Disponível após salvar</dd></dl><p>Revise os dados nesta página e confirme em Salvar cadastro.</p></section></aside></div>
<div class="single-actions"><span>NGI Carajás · Cadastro patrimonial</span><div><a class="btn" href="{{ url_for('ficha', bem_id=registro.id) if registro else url_for('listar_bens') }}">Cancelar</a><button class="btn primary" type="submit" id="salvar-bem">{{ 'Salvar alterações' if registro else 'Salvar cadastro' }}</button></div></div>
</form>
<dialog id="base-dialog" class="base-dialog"><form method="post" id="base-rapida"><div class="section-top"><div><h2>Cadastrar base ou local</h2><p>O novo local ficará disponível nesta lista.</p></div><button type="button" class="text-action" id="fechar-base" aria-label="Fechar cadastro de base">Fechar</button></div><input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
{% include 'campos_base' %}<p id="base-erro" class="inline-error" role="alert"></p><div class="dialog-actions"><button class="btn primary" type="submit" id="salvar-base-rapida">Salvar base e selecionar</button></div></form></dialog>
<script>
const basesCadastradas = {{ bases_json|tojson }};
const formBem=document.querySelector('#bem-form');
const statusSerie=document.querySelector('#serie_excecao');
const baseSelect=document.querySelector('#base_id');
let sendingBem=false;
function atualizarSerie(){const informado=statusSerie.value==='Informado';document.querySelector('#serie-area').hidden=!informado;document.querySelector('#serie').required=informado;document.querySelector('#justificativa-serie-area').hidden=informado;document.querySelector('#serie_justificativa').required=!informado;}
function atualizarPlaqueta(){const p=document.querySelector('#possui_plaqueta');if(p){const sim=p.value==='sim';document.querySelector('#plaqueta-area').hidden=!sim;['plaqueta_original','origem'].forEach(id=>document.getElementById(id).required=sim);}document.querySelector('#resumo-plaqueta').textContent={{ (registro.numero_ngi if registro else '')|tojson }}||(p&&p.value==='sim'?'Número sai da plaqueta antiga':'Nº de patrimônio após salvar');}
function atualizarBase(){const base=basesCadastradas.find(b=>String(b.id)===baseSelect.value);document.querySelector('#base-detalhes').hidden=!base;document.querySelector('#resumo-local').textContent=base?base.nome:'Selecione uma base';if(!base)return;document.querySelector('#base-endereco').textContent=base.endereco;document.querySelector('#base-coordenadas').textContent=`Latitude ${base.latitude} · Longitude ${base.longitude}`;document.querySelector('#base-mapa').href=`https://www.google.com/maps?q=${encodeURIComponent(base.latitude)},${encodeURIComponent(base.longitude)}`;}
statusSerie.addEventListener('change',atualizarSerie);
const possui=document.querySelector('#possui_plaqueta');if(possui)possui.addEventListener('change',atualizarPlaqueta);
baseSelect.addEventListener('change',atualizarBase);
function validarComplementos(){const motivo=document.querySelector('#serie_justificativa');motivo.setCustomValidity(statusSerie.value!=='Informado'&&motivo.value.trim().length<10?'Justifique com pelo menos 10 caracteres.':'');const aq=document.querySelector('#aquisicao_justificativa');const falta=!document.querySelector('#data_aquisicao').value||!document.querySelector('#valor').value.trim();aq.required=falta;aq.setCustomValidity(falta&&aq.value.trim().length<10?'Justifique a data ou o valor não informado com pelo menos 10 caracteres.':'');}
formBem.addEventListener('input',()=>{document.querySelector('#resumo-nome').textContent=document.querySelector('#nome').value.trim()||'Novo bem';validarComplementos();});
let previewUrl;document.querySelector('#foto').addEventListener('change',function(){const img=document.querySelector('#preview');img.onerror=()=>{img.hidden=true;};if(previewUrl)URL.revokeObjectURL(previewUrl);img.hidden=true;if(this.files[0]){if(this.files[0].size>10*1024*1024){alert('Escolha uma foto de até 10 MB.');this.value='';return;}previewUrl=URL.createObjectURL(this.files[0]);img.src=previewUrl;img.hidden=false;const remover=document.querySelector('[name=remover_foto]');if(remover)remover.checked=false;}});
formBem.addEventListener('submit',e=>{if(sendingBem){e.preventDefault();return;}validarComplementos();if(!formBem.reportValidity()){e.preventDefault();return;}sendingBem=true;const btn=document.querySelector('#salvar-bem');btn.disabled=true;btn.textContent='Salvando…';});
window.addEventListener('pageshow',()=>{sendingBem=false;const b=document.querySelector('#salvar-bem');b.disabled=false;b.textContent={{ ('Salvar alterações' if registro else 'Salvar cadastro')|tojson }};});
const dialogBase=document.querySelector('#base-dialog');
document.querySelector('#abrir-base').addEventListener('click',()=>{document.querySelector('#base-erro').textContent='';dialogBase.showModal();});
document.querySelector('#fechar-base').addEventListener('click',()=>dialogBase.close());
const formBase=document.querySelector('#base-rapida');
formBase.addEventListener('submit',async e=>{e.preventDefault();const erro=document.querySelector('#base-erro');const btn=document.querySelector('#salvar-base-rapida');erro.textContent='';if(!formBase.reportValidity())return;btn.disabled=true;btn.textContent='Salvando…';try{const resposta=await fetch({{ url_for('cadastros')|tojson }},{method:'POST',headers:{Accept:'application/json'},body:new FormData(formBase)});if(resposta.redirected){erro.textContent='Sua sessão expirou. Copie os dados preenchidos antes de entrar novamente.';return;}const tipo=resposta.headers.get('content-type')||'';if(!tipo.includes('application/json')){erro.textContent='Não foi possível salvar. Sua sessão ou formulário pode ter expirado. Preserve os dados antes de atualizar.';return;}const dados=await resposta.json();if(!resposta.ok){erro.textContent=(dados.erros||['Não foi possível salvar a base.']).join(' ');return;}basesCadastradas.push(dados.base);const option=document.createElement('option');option.value=String(dados.base.id);option.textContent=dados.base.nome;baseSelect.append(option);baseSelect.value=String(dados.base.id);atualizarBase();formBase.reset();dialogBase.close();}catch(e){erro.textContent='Falha de conexão. Seus dados continuam nesta tela; tente novamente.';}finally{btn.disabled=false;btn.textContent='Salvar base e selecionar';}});
atualizarSerie();atualizarPlaqueta();atualizarBase();validarComplementos();

</script>
"""
CAMPOS_BASE_TEMPLATE = r"""
<div class="fields">
<div class="field wide"><label for="base-nome">Nome da base / escritório / local *</label><input id="base-nome" name="nome" maxlength="160" required value="{{ base_valores.get('nome','') if base_valores else '' }}" placeholder="Ex.: Base Gavião Real"></div>
<div class="field wide"><label for="base-endereco-campo">Endereço ou referência física *</label><textarea id="base-endereco-campo" name="endereco" maxlength="300" required placeholder="Endereço, município/UF ou referência de acesso">{{ base_valores.get('endereco','') if base_valores else '' }}</textarea></div>
<div class="field"><label for="base-latitude">Latitude *</label><input id="base-latitude" name="latitude" inputmode="decimal" required value="{{ base_valores.get('latitude','') if base_valores else '' }}" placeholder="Ex.: -6,0800000"><small>Entre -90 e 90.</small></div>
<div class="field"><label for="base-longitude">Longitude *</label><input id="base-longitude" name="longitude" inputmode="decimal" required value="{{ base_valores.get('longitude','') if base_valores else '' }}" placeholder="Ex.: -50,1500000"><small>Entre -180 e 180.</small></div>
{% if base_editando %}<div class="field wide"><label for="base-ativo">Disponibilidade no cadastro de bens</label><select id="base-ativo" name="ativo"><option value="sim" {{ 'selected' if base_valores.get('ativo') == 'sim' }}>Ativa</option><option value="nao" {{ 'selected' if base_valores.get('ativo') == 'nao' }}>Inativa · Preservar vínculos existentes</option></select></div><input type="hidden" name="revisao" value="{{ base_valores.get('revisao',base_editando.revisao) }}">{% endif %}
</div>
"""
REGISTRO_NAVEGACAO_TEMPLATE = r"""
<nav class="registry-navigation" aria-label="Navegação de {{ cadastro_titulo }}">
<a href="{{ url_for(registro_endpoint) }}" class="{{ 'current' if not registro_formulario }}" {% if not registro_formulario %}aria-current="page"{% endif %}>{{ registro_rotulo_lista }}</a>
{% if not usuario.leitura %}<a href="{{ request.path if registro_editando else url_for(registro_endpoint, aba='cadastro') }}" class="{{ 'current' if registro_formulario }}" {% if registro_formulario %}aria-current="page"{% endif %}>{{ 'Editar cadastro' if registro_editando else registro_rotulo_novo }}</a>{% endif %}
</nav>
"""
REGISTRO_FILTROS_TEMPLATE = r"""
<form method="get" action="{{ url_for(registro_endpoint) }}" class="registry-toolbar" role="search">
<div class="field"><label for="registro-busca">Pesquisar {{ cadastro_titulo|lower }}</label><input id="registro-busca" type="search" name="q" maxlength="120" value="{{ registro_busca }}" placeholder="{{ registro_placeholder }}"></div>
<div class="field"><label for="registro-status">Situação</label><select id="registro-status" name="situacao"><option value="">Todas</option><option value="ativos" {{ 'selected' if registro_situacao == 'ativos' }}>Ativos</option><option value="inativos" {{ 'selected' if registro_situacao == 'inativos' }}>Inativos</option></select></div>
<button class="btn primary" type="submit">Pesquisar</button>{% if registro_busca or registro_situacao %}<a class="btn" href="{{ url_for(registro_endpoint) }}">Limpar</a>{% endif %}
</form>
"""
REGISTRO_PAGINACAO_TEMPLATE = r"""
<div class="pagination-bar"><span>{{ primeiro_registro }}–{{ ultimo_registro }} de {{ total_registros }} registros{% if registro_busca or registro_situacao %} encontrados{% endif %}</span><nav class="pagination" aria-label="Páginas de {{ cadastro_titulo }}">
{% if pagina_registro > 1 %}<a href="{{ url_for(registro_endpoint, pagina=pagina_registro-1, q=registro_busca, situacao=registro_situacao) }}">Anterior</a>{% endif %}
{% for n in numeros_registro %}{% if not loop.first and n > numeros_registro[loop.index0-1]+1 %}<span class="page-gap">…</span>{% endif %}{% if n == pagina_registro %}<span class="current-page" aria-current="page">{{ n }}</span>{% else %}<a href="{{ url_for(registro_endpoint, pagina=n, q=registro_busca, situacao=registro_situacao) }}">{{ n }}</a>{% endif %}{% endfor %}
{% if pagina_registro < paginas_registro %}<a href="{{ url_for(registro_endpoint, pagina=pagina_registro+1, q=registro_busca, situacao=registro_situacao) }}">Próxima</a>{% endif %}</nav></div>
"""
CADASTROS_TEMPLATE = r"""
<div class="single-heading"><div><h1>Bases e locais</h1><p>Gerencie as bases, escritórios e locais do patrimônio.</p></div></div>
{% include 'registro_navegacao' %}
{% if base_erros %}<div class="erros" role="alert"><ul>{% for erro in base_erros %}<li>{{ erro }}</li>{% endfor %}</ul></div>{% endif %}
<div class="registry-workspace">{% if not registro_formulario %}<section class="panel registry-list"><div class="panelhead"><div><h2>Bases e locais</h2><p>{{ total_registros }} registros · 25 por página</p></div></div>
{% include 'registro_filtros' %}
<div class="tablewrap"><table><thead><tr><th>Local / endereço</th><th>Coordenadas</th><th>Situação</th><th></th></tr></thead><tbody>
{% for base in bases_registro %}<tr data-base-search="{{ (base.nome ~ ' ' ~ base.endereco)|lower }}"><td><strong>{{ base.nome }}</strong><small class="table-sub">{{ base.endereco }}</small></td><td class="coords-cell"><a href="https://www.google.com/maps?q={{ base.latitude }},{{ base.longitude }}" target="_blank" rel="noopener noreferrer">{{ base.latitude }}<br>{{ base.longitude }}</a></td><td><span class="badge">{{ 'Ativa' if base.ativo else 'Inativa' }}</span></td><td>{% if not usuario.leitura %}<a class="text-action" href="{{ url_for('editar_base', base_id=base.id) }}">Editar</a>{% endif %}</td></tr>{% endfor %}
</tbody></table></div>{% if not bases_registro %}<div class="empty">Nenhum local encontrado. Ajuste os filtros ou use a aba Cadastrar base.</div>{% endif %}{% include 'registro_paginacao' %}<p class="hint">Bases inativas não aparecem para novos vínculos. Os registros existentes são preservados.</p></section>
{% else %}<section class="form-section registry-form"><h2>{{ 'Editar local' if base_editando else 'Nova base ou local' }}</h2><p>Cadastre uma vez e selecione o local nos próximos bens.</p>
<form method="post" action="{{ url_for('editar_base', base_id=base_editando.id) if base_editando else url_for('cadastros') }}">
<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">{% include 'campos_base' %}
<div class="dialog-actions"><a class="btn" href="{{ url_for('cadastros') }}">Cancelar</a><button type="submit" class="btn primary">{{ 'Salvar alterações' if base_editando else 'Cadastrar local' }}</button></div>
{% if base_editando %}<small class="hint">Mudanças no nome, endereço ou coordenadas também serão aplicadas aos bens vinculados, com registro no histórico.</small>{% endif %}
</form></section>{% endif %}</div>

"""

LISTA_BENS_TEMPLATE = r"""
<div class="list-heading"><div><h1>Bens patrimoniais <span>{{ quantidade }}</span></h1><p>Consulte, localize e gerencie os bens do NGI Carajás.</p></div></div>
<nav class="registry-navigation" aria-label="Navegação dos bens"><a href="{{ url_for('listar_bens') }}" class="current" aria-current="page">Bens cadastrados</a>{% if not usuario.leitura %}<a href="{{ url_for('cadastrar_bem') }}" >Cadastrar bem</a><a href="{{ url_for('entradas_sigad') }}">Entradas do SIGAD{% if entradas_sigad_pendentes %} ({{ entradas_sigad_pendentes }}){% endif %}</a>{% endif %}</nav>
<section class="panel asset-register">
<form method="get" action="{{ url_for('listar_bens') }}" class="list-filters" role="search">
<div class="list-search"><label for="busca-bens">Buscar no patrimônio</label><input type="search" id="busca-bens" name="q" maxlength="120" value="{{ q }}" placeholder="Nome, série, plaqueta ou responsável"></div>
<div><label for="f-convenio">Convênio</label><select id="f-convenio" name="convenio"><option value="">Todos os convênios</option>{% for c in convenios %}<option {{ 'selected' if filtro_convenio == c }}>{{ c }}</option>{% endfor %}</select></div>
<div><label for="f-categoria">Categoria</label><select id="f-categoria" name="categoria_id"><option value="">Todas as categorias</option>{% for c in categorias_filtro %}<option value="{{ c.id }}" {{ 'selected' if categoria_selecionada==c.id }}>{{ c.nome }}</option>{% endfor %}</select></div>
<div><label for="f-local">Base / local</label><select id="f-local" name="local"><option value="">Todos os locais</option>{% for l in inv_locais %}<option {{ 'selected' if filtro_local == l }}>{{ l }}</option>{% endfor %}</select></div>
<div><label for="f-situacao">Situação</label><select id="f-situacao" name="situacao"><option value="">Todas</option>{% for s in situacoes %}<option {{ 'selected' if filtro_situacao == s }}>{{ s }}</option>{% endfor %}</select></div>
<div><label for="f-acervo">Acervo</label><select id="f-acervo" name="acervo">{% for key,label in [('ativos','Ativos'),('baixados','Baixados'),('todos','Todos')] %}<option value="{{ key }}" {{ 'selected' if acervo==key }}>{{ label }}</option>{% endfor %}</select></div>
<div><label for="f-ordem">Ordenar por</label><select id="f-ordem" name="ordem">{% for key,label in [('recentes','Mais recentes'),('nome','Nome do bem'),('local','Base / local'),('valor','Maior valor')] %}<option value="{{ key }}" {{ 'selected' if ordenacao == key }}>{{ label }}</option>{% endfor %}</select></div>
<div><label for="f-nota">Nota fiscal</label><select id="f-nota" name="nota">{% for key,label in [('','Todas'),('com','Com nota'),('sem','Sem nota')] %}<option value="{{ key }}" {{ 'selected' if filtro_nota==key }}>{{ label }}</option>{% endfor %}</select></div>
<div><label for="f-classif">É patrimônio?</label><select id="f-classif" name="classificacao"><option value="">Todos os itens</option>{% for c in classificacoes %}<option value="{{ c }}" {{ 'selected' if filtro_classif==c }}>{{ 'Só patrimônio' if c=='Patrimônio' else 'Só não patrimônio' }}</option>{% endfor %}</select></div>
<div><label for="f-ingresso">Forma de entrada</label><select id="f-ingresso" name="ingresso"><option value="">Todas</option>{% for f in formas_ingresso %}<option value="{{ f }}" {{ 'selected' if filtro_ingresso==f }}>{{ f }}</option>{% endfor %}</select></div>
<button class="btn primary" type="submit">Buscar</button>{% if q or filtro_convenio or filtro_local or filtro_situacao or filtro_nota or filtro_classif or filtro_ingresso or categoria_selecionada or acervo != 'ativos' %}<a class="text-action" href="{{ url_for('listar_bens') }}">Limpar</a>{% endif %}
</form>
<div class="list-meta"><span>{{ total_filtrado }} {{ 'bem encontrado' if total_filtrado == 1 else 'bens encontrados' }}</span><span>25 por página</span></div>
<div class="tablewrap compact-table"><table><colgroup><col class="col-photo"><col class="col-plaque"><col class="col-name"><col class="col-category"><col class="col-serial"><col class="col-local"><col class="col-person"><col class="col-status"><col class="col-actions"></colgroup><thead><tr><th class="photo-header">Foto</th><th>Plaqueta</th><th>Bem</th><th>Categoria</th><th>Número de série</th><th>Base / local</th><th>Responsável</th><th>Situação</th><th class="actions-col">Ações</th></tr></thead><tbody>
{% for b in bens %}<tr class="{{ 'highlight-row' if b.id == destaque }}" data-bem-id="{{ b.id }}">
<td class="photo-cell"><a class="row-photo" href="{{ url_for('ficha', bem_id=b.id) }}" aria-label="Ver foto e ficha de {{ b.nome }}">{% if b.tem_foto %}<img loading="lazy" src="{{ url_for('foto_bem', bem_id=b.id) }}" alt="Foto de {{ b.nome }}">{% else %}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="8" cy="9" r="1.5"/><path d="m4 18 5-6 4 4 3-3 5 5"/></svg>{% endif %}</a></td>
<td class="plaque-cell">{% if b.numero_ngi %}<strong>{{ b.numero_ngi }}</strong>{% elif b.plaqueta_original %}<strong>{{ b.plaqueta_original }}</strong><small>{{ b.origem }}</small>{% else %}<span class="pending-text">Sem plaqueta</span>{% if not usuario.leitura and not b.encerrado %}<form method="post" action="{{ url_for('gerar_plaqueta', bem_id=b.id) }}"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><input type="hidden" name="voltar_lista" value="sim"><button type="submit" class="row-link">Gerar número</button></form>{% endif %}{% endif %}</td>
<td><div class="list-asset"><div><a class="asset-name" href="{{ url_for('ficha', bem_id=b.id) }}">{{ b.nome }}</a><small>{{ b.marca }} · {{ b.modelo }}</small></div></div></td>
<td>{{ b.categoria or 'Sem categoria' }}</td><td class="serial-cell">{{ b.serie or b.serie_excecao }}</td><td><span>{{ b.local }}</span><small>{{ b.convenio }}</small></td><td>{{ b.responsavel }}</td><td><span class="badge {{ 'warn' if b.situacao == 'Manutenção' else 'field' if b.situacao == 'Em campo' else '' }}">{{ 'Baixado' if b.encerrado else b.situacao }}</span></td>
<td class="row-actions"><a href="{{ url_for('ficha', bem_id=b.id) }}" aria-label="Ver {{ b.nome }}">Ver</a>{% if not usuario.leitura and not b.encerrado %}<a href="{{ url_for('editar_bem', bem_id=b.id) }}" aria-label="Editar {{ b.nome }}">Editar</a>{% endif %}</td></tr>
{% else %}<tr><td colspan="9" class="list-empty">{% if quantidade or acervo != 'ativos' %}Nenhum bem corresponde à busca. Ajuste ou limpe os filtros.{% else %}Nenhum bem cadastrado. Clique em Cadastrar bem para começar.{% endif %}</td></tr>{% endfor %}
</tbody></table></div>
<div class="pagination-bar"><span>Exibindo {{ primeiro }}–{{ ultimo }} de {{ total_filtrado }}</span><nav class="pagination" aria-label="Páginas dos bens">
{% if pagina > 1 %}<a href="{{ url_pagina(pagina-1) }}" aria-label="Página anterior">Anterior</a>{% endif %}
{% for n in numeros_paginas %}{% if not loop.first and n > numeros_paginas[loop.index0-1]+1 %}<span class="page-gap">…</span>{% endif %}{% if n == pagina %}<span class="current-page" aria-current="page">{{ n }}</span>{% else %}<a href="{{ url_pagina(n) }}" aria-label="Página {{ n }}">{{ n }}</a>{% endif %}{% endfor %}
{% if pagina < paginas %}<a href="{{ url_pagina(pagina+1) }}" aria-label="Próxima página">Próxima</a>{% endif %}</nav></div>
</section>
"""
VISAO_GERAL_TEMPLATE = r'''<section class="mobile-home" aria-label="Visão geral no celular">
<header class="mh-header"><div class="mh-brand-row"><a class="mh-brand mh-brand-dourada" href="{{ url_for('inicio') }}"><span><strong>Patrimônio Carajás</strong><small>NGI ICMBIO CARAJÁS</small></span></a><span class="mh-avatar" aria-label="{{ usuario.nome }}">{{ iniciais }}</span></div><p class="mh-greeting">{{ saudacao_mobile }}, {{ usuario.nome.split()[0] }}</p><div class="mh-total"><strong>{{ quantidade }}</strong><span>bens no acervo</span></div><p class="mh-totals">{% for nome,n in por_convenio %}{{ ' · ' if not loop.first }}{{ nome or 'Sem convênio' }} {{ n }}{% endfor %}</p></header>
<div class="mh-content"><section class="mh-inventory mh-card"><div class="mh-progress-row"><div class="mh-progress" role="img" aria-label="{{ percentual }}% do acervo conferido"><svg viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="26"/><circle class="mh-progress-fill" cx="32" cy="32" r="26" pathLength="100" stroke-dasharray="{{ percentual }} 100" transform="rotate(-90 32 32)"/></svg><strong>{{ percentual }}%</strong></div><div class="mh-inventory-text"><small>{{ 'Inventário em andamento' if campanha_atual else 'Nenhum inventário em andamento' }}</small>{% if campanha_atual %}<h2>{{ campanha_atual.nome }} · {{ campanha_atual.local }}</h2><p>Acervo: {{ conferidos }} de {{ quantidade }} conferidos · faltam {{ quantidade-conferidos }}</p>{% else %}<h2>Organize a próxima conferência</h2><p>{{ conferidos }} de {{ quantidade }} bens do acervo conferidos.</p>{% endif %}</div></div>
{% if usuario.leitura %}<a class="mh-primary" href="{{ url_for('listar_bens') }}">{{ icon('box') }} Ver bens</a>{% elif campanha_atual %}{% if not usuario.leitura %}<button type="button" class="mh-primary" data-home-camera="inventory">{{ icon('scan') }} Continuar conferência</button>{% else %}<a class="mh-primary" href="{{ url_for('inventario_detalhe',inventario_id=campanha_atual.id) }}">{{ icon('check') }} Consultar inventário</a>{% endif %}{% else %}<a class="mh-primary" href="{{ url_for('inventario',aba='cadastro') if not usuario.leitura else url_for('inventario') }}">{{ icon('check') }} {{ 'Iniciar inventário' if not usuario.leitura else 'Consultar inventários' }}</a>{% endif %}</section>
{% set attention=pendentes_mov or atrasados or baixas_analise or convenios_vencendo %}<section class="mh-card mh-attention"><div class="mh-attention-title"><span class="mh-check {{ 'mh-warning' if attention }}">{{ icon('clock' if attention else 'check') }}</span><div><h2>{{ 'Precisa de atenção' if attention else 'Tudo em dia' }}</h2><p>{{ 'Confira as pendências abaixo' if attention else 'sem pendências fora do inventário' }}</p></div></div><div class="mh-status-grid">{% for label,n,url,danger,desc in [('Movimentações',pendentes_mov,url_for('movimentacoes',status='Pendente'),false,'aguardando entrega'),('Devoluções',atrasados,url_for('movimentacoes',status='atrasados'),true,'em atraso'),('Baixas',baixas_analise,url_for('baixas'),false,'em análise'),('Convênios',convenios_vencendo,url_for('encerramento_convenios'),false,'com término em até 90 dias')] %}<a class="mh-status {{ ('mh-danger' if danger else 'mh-warning') if n }}" href="{{ url }}"><span class="mh-check">{{ icon('clock' if n else 'check') }}</span><span>{{ label }}{% if n %}<small>{{ n }} {{ desc }}</small>{% endif %}</span></a>{% endfor %}</div></section>
{% if not usuario.leitura %}<div class="mh-actions"><a class="mh-card" href="{{ url_for('cadastrar_bem') }}"><span aria-hidden="true">＋</span><strong>Cadastrar bem</strong></a><a class="mh-card" href="{{ url_for('movimentacoes',aba='cadastro') }}">{{ icon('move') }}<strong>Movimentar bem</strong></a></div>{% endif %}</div>
</section>

<div class="desktop-overview">
<div class="home19-heading"><div><h1>Página inicial</h1><p>Acompanhe o patrimônio e acesse suas rotinas.</p></div><div class="dashboard-top-actions"><a class="btn" href="{{ url_for('leitor_qr') }}">{{ icon('scan') }} Ler QR Code</a>{% if not usuario.leitura %}<a class="btn primary" href="{{ url_for('cadastrar_bem') }}"><span aria-hidden="true">＋</span> Cadastrar bem</a>{% endif %}</div></div>
<div class="home19-kpis home19-kpis-3">
<a class="home19-kpi" href="{{ url_for('listar_bens') }}"><div class="home19-kpi-main"><span class="home19-icon">{{ icon('box') }}</span><div><span>Bens ativos</span><strong>{{ quantidade }}</strong></div></div><small>Bens que integram o acervo ativo.</small></a>
<a class="home19-kpi" href="{{ url_for('inventario') }}"><div class="home19-kpi-main"><span class="home19-icon amber">{{ icon('doc') }}</span><div><span>A conferir no acervo</span><strong>{{ quantidade-conferidos }}</strong></div></div><small>Bens sem conferência válida no cadastro atual.</small></a>
<a class="home19-kpi" href="{{ url_for('inicio') }}#home-attention"><div class="home19-kpi-main"><span class="home19-icon red">{{ icon('clock') }}</span><div><span>Pendências</span><strong>{{ pendentes_mov+atrasados+baixas_analise+convenios_vencendo }}</strong></div></div><small>Movimentações, devoluções, baixas e convênios.</small></a>
</div>
<section class="home25-shortcuts" aria-label="Acesso rápido"><h2>Acesso rápido</h2><div class="home25-shortcut-grid">{% for label,ico,url,desc in [('Consultar bens','box',url_for('listar_bens'),'Pesquise e visualize os bens.'),('Registrar movimentação' if not usuario.leitura else 'Consultar movimentações','move',url_for('movimentacoes',aba='cadastro') if not usuario.leitura else url_for('movimentacoes'),'Transferências, entregas e devoluções.'),('Continuar inventário' if campanha_atual else 'Consultar inventários','check',url_for('inventario'),'Acompanhe a conferência dos bens.'),('Imprimir plaquetas','doc',url_for('plaquetas_lote'),'Etiquetas de identificação.')] %}<a href="{{ url }}"><span class="home25-shortcut-icon">{{ icon(ico) }}</span><div><strong>{{ label }}</strong><small>{{ desc }}</small></div><span aria-hidden="true">›</span></a>{% endfor %}</div></section><div class="home25-workspace"><section class="panel home19-assets" id="home-assets"><div class="home19-section-title"><div><h2>Bens patrimoniais</h2><p>Consulte os bens ativos cadastrados no sistema.</p></div><a class="text-action" href="{{ url_for('listar_bens') }}">Ver todos os bens →</a></div><form method="get" action="{{ url_for('inicio') }}#home-assets" class="home19-filters"><div><label class="visually-hidden" for="home-q">Buscar bens</label><input id="home-q" type="search" name="q" maxlength="120" value="{{ home_busca }}" placeholder="Buscar por nome, série ou patrimônio…"></div><div><label class="visually-hidden" for="home-local">Local</label><select id="home-local" name="local"><option value="">Todos os locais</option>{% for l in locais %}<option {{ 'selected' if home_local==l }}>{{ l }}</option>{% endfor %}</select></div><div><label class="visually-hidden" for="home-cat">Categoria</label><select id="home-cat" name="categoria_id"><option value="">Todas as categorias</option>{% for cat in categorias_home %}<option value="{{ cat.id }}" {{ 'selected' if home_categoria==cat.id }}>{{ cat.nome }}</option>{% endfor %}</select></div><button class="btn primary">Filtrar</button>{% if home_busca or home_local or home_categoria %}<a class="text-action" href="{{ url_for('inicio') }}#home-assets">Limpar</a>{% endif %}</form><div class="tablewrap"><table class="home19-table"><thead><tr><th>Bem</th><th>Patrimônio</th><th>Local</th><th>Convênio</th><th>Situação</th><th>Ações</th></tr></thead><tbody>{% for b in rows %}<tr><td><div class="home19-asset-name"><a class="home19-thumb" href="{{ url_for('ficha',bem_id=b.id,consulta=1) }}" aria-label="Abrir ficha de {{ b.nome }}">{% if b.tem_foto %}<img loading="lazy" src="{{ url_for('foto_bem',bem_id=b.id) }}" alt="Foto de {{ b.nome }}">{% else %}{{ icon('box') }}{% endif %}</a><div><strong>{{ b.nome }}</strong><small>{{ b.marca or '' }} {{ b.modelo or '' }}</small></div></div></td><td>{{ b.numero_ngi or b.plaqueta_original or 'Sem identificação' }}</td><td>{{ b.local }}</td><td>{{ b.convenio or 'Não identificado' }}</td><td><span class="badge {{ 'warn' if b.situacao not in ['Em uso','Armazenado'] }}">{{ b.situacao }}</span></td><td><a class="text-action" href="{{ url_for('ficha',bem_id=b.id,consulta=1) }}">Abrir ficha →</a></td></tr>{% else %}<tr><td colspan="6" class="list-empty">Nenhum bem encontrado. Ajuste os filtros ou cadastre o primeiro bem.</td></tr>{% endfor %}</tbody></table></div>{% include 'op_paginacao' %}<p class="home19-scope">Os filtros acima se aplicam à lista. Os indicadores mostram todo o acervo ativo.</p></section>
<aside class="home25-aside" aria-label="Inventário e pendências"><section class="home25-inventory"><small>{{ 'Inventário em andamento' if campanha_atual else 'Nenhum inventário aberto' }}</small><h2>{{ campanha_atual.nome if campanha_atual else 'Organize a conferência' }}</h2>{% if campanha_atual %}<p>{{ campanha_atual.local }}</p>{% endif %}<div class="home25-percent"><strong>{{ percentual }}%</strong><span>do acervo conferido</span></div><progress value="{{ conferidos }}" max="{{ quantidade or 1 }}" aria-label="Conferência do acervo ativo"></progress><p>{{ conferidos }} de {{ quantidade }} bens do acervo ativo conferidos.</p><a class="btn" href="{{ url_for('inventario') }}">{{ 'Consultar inventário' if usuario.leitura else 'Continuar conferência' if campanha_atual else 'Iniciar inventário' }}</a><small>O percentual representa o acervo ativo; pode diferir do inventário selecionado.</small></section><section class="panel home25-pending" id="home-attention"><h2>{{ 'Precisa de atenção' if pendentes_mov+atrasados+baixas_analise+convenios_vencendo else 'Tudo em dia' }}</h2>{% for label,n,url,danger in [('Movimentações aguardando entrega',pendentes_mov,url_for('movimentacoes',status='Pendente'),false),('Devoluções atrasadas',atrasados,url_for('movimentacoes',status='atrasados'),true),('Baixas em análise',baixas_analise,url_for('baixas'),false),('Convênios com término em até 90 dias',convenios_vencendo,url_for('encerramento_convenios'),false)] %}<a href="{{ url }}" class="{{ 'has-pending' if n }} {{ 'is-overdue' if danger and n }}"><span>{{ icon('clock' if n else 'check') }}</span><div><strong>{{ n }}</strong> {{ label }}</div><span aria-hidden="true">›</span></a>{% endfor %}</section></aside></div><details class="panel home19-attention"><summary>Pendências e atividades</summary><div class="home19-attention-links"><a href="{{ url_for('movimentacoes',status='Pendente') }}">{{ pendentes_mov }} movimentações aguardando entrega →</a><a href="{{ url_for('baixas') }}">{{ baixas_analise }} processos de baixa em análise →</a><a href="{{ url_for('encerramento_convenios') }}">{{ convenios_vencendo }} convênios com término nos próximos 90 dias →</a></div><h2>Últimas movimentações</h2><div class="tablewrap"><table><thead><tr><th>Bem</th><th>Origem</th><th>Destino</th><th>Situação</th><th></th></tr></thead><tbody>{% for m in recentes %}<tr><td>{{ m.origem.nome }}</td><td>{{ m.origem.local }}</td><td>{{ m.destino.local }}</td><td>{{ m.status }}</td><td><a class="text-action" href="{{ url_for('movimento_detalhe',movimento_id=m.id) }}">Abrir</a></td></tr>{% else %}<tr><td colspan="5">Nenhuma movimentação registrada.</td></tr>{% endfor %}</tbody></table></div></details>

</div>'''
FICHA_COMPACTA_TEMPLATE = r'''
{% if not usuario.leitura and request.args.get('consulta')!='1' %}<script>if(window.matchMedia('(max-width:768px)').matches){const u=new URL({{ url_for('inventario_campo')|tojson }},location.origin);u.searchParams.set('codigo',{{ (PUBLIC_URL_MOBILE ~ url_for('ficha',bem_id=bem.id))|tojson }});location.replace(u.pathname+u.search);}</script>{% endif %}

<a class="back" href="{{ url_for('listar_bens',acervo='todos' if bem.encerrado else 'ativos') }}">← Bens patrimoniais</a>
<div class="asset-profile-head"><div class="asset-profile-photo">{% if bem.tem_foto %}<img src="{{ url_for('foto_bem',bem_id=bem.id) }}" alt="Foto de {{ bem.nome }}">{% else %}<span>Sem foto</span>{% endif %}</div><div class="asset-profile-title"><small>{{ bem.patrimonio }}</small><h1>{{ bem.nome }}</h1><div class="asset-badges"><span class="badge {{ 'warn' if bem.encerrado }}">{{ 'Baixado' if bem.encerrado else bem.situacao }}</span><span class="badge">{{ bem.conservacao }}</span><span class="badge">Etiqueta: {{ bem.etiqueta_situacao }}</span>{% if entrega %}<span class="badge warn">{{ 'Devolução vencida' if entrega.previsao_retorno and entrega.previsao_retorno < hoje_ficha else 'Entrega temporária aberta' }}</span>{% endif %}</div></div></div>
<div class="asset-profile-actions">{% if pode_acessar('imprimir_plaqueta') %}<a class="btn" href="{{ url_for('imprimir_plaqueta',bem_id=bem.id) }}">Imprimir plaqueta</a>{% endif %}{% if not usuario.leitura and not bem.encerrado %}<a class="btn" href="{{ url_for('editar_bem',bem_id=bem.id) }}">Editar cadastro</a><a class="btn primary" href="{{ url_for('movimentacoes',aba='cadastro',bem_id=bem.id,retorno_de=entrega.id) if entrega else url_for('movimentacoes',aba='cadastro',bem_id=bem.id) }}">{{ 'Registrar devolução' if entrega else 'Movimentar bem' }}</a>{% endif %}{% if item_campanha and not usuario.leitura %}<a class="btn" href="{{ url_for('conferir_inventario',item_id=item_campanha.id,campo='sim') }}">Conferir no inventário aberto</a>{% endif %}</div>
{% if bem.encerrado %}<div class="callout"><strong>Baixa registrada em {{ bem.encerrado_em|datahora }}</strong><p>O cadastro, os documentos e o histórico estão preservados.</p></div>{% endif %}
<div class="asset-profile-layout"><div class="asset-profile-main"><section class="panel"><h2>Identificação e aquisição</h2><p class="detail-description">{{ bem.descricao }}</p><dl class="compact-facts">{% for label,key in [('Categoria','categoria'),('Marca','marca'),('Modelo','modelo'),('Número de série','serie'),('Plaqueta original','plaqueta_original'),('Origem da plaqueta','origem'),('Nº de patrimônio','numero_ngi'),('Forma de entrada','forma_ingresso'),('Doador / processo de origem','ingresso_detalhe'),('Convênio / projeto','convenio'),('Coordenação responsável','coordenacao')] %}{% if bem[key] %}<div><dt>{{ label }}</dt><dd>{{ bem[key] }}</dd></div>{% endif %}{% endfor %}<div><dt>Data de aquisição</dt><dd>{{ bem.data_aquisicao|datahora }}</dd></div><div><dt>Valor de aquisição</dt><dd>{{ bem.valor|brl }}</dd></div><div><dt>Classificação</dt><dd><span class="badge {{ 'warn' if bem.classificacao!='Patrimônio' }}">{{ 'Patrimônio' if bem.classificacao=='Patrimônio' else 'Não é patrimônio · controle simples' }}</span>{% if bem.classificacao_justificativa %}<small class="table-sub">Fora da regra dos R$ 250,00: {{ bem.classificacao_justificativa }}</small>{% endif %}</dd></div><div><dt>Nota fiscal</dt><dd>{{ bem.nota_fiscal or 'Não informada' }}{% if bem.nota_fiscal_anexada %} · <a href="{{ url_for('nota_fiscal_bem', bem_id=bem.id) }}" target="_blank" rel="noopener">abrir arquivo</a>{% endif %}</dd></div>{% if bem.fornecedor %}<div><dt>Fornecedor</dt><dd>{{ bem.fornecedor }}</dd></div>{% endif %}{% if bem.serie_excecao!='Informado' %}<div><dt>Número de série</dt><dd>{{ bem.serie_excecao }} · {{ bem.serie_justificativa }}</dd></div>{% endif %}</dl></section>
<section class="panel"><h2>Localização e responsabilidade</h2><dl class="compact-facts">{% for label,key in [('Local atual','local'),('Endereço / referência','endereco'),('Sala / complemento','complemento'),('Responsável atual','responsavel'),('Contato','responsavel_contato')] %}{% if bem[key] %}<div><dt>{{ label }}</dt><dd>{{ bem[key] }}</dd></div>{% endif %}{% endfor %}{% if bem.latitude is not none %}<div><dt>Localização no mapa</dt><dd><a class="content-link" href="https://www.google.com/maps?q={{ bem.latitude }},{{ bem.longitude }}" target="_blank" rel="noopener noreferrer">{{ bem.latitude }}, {{ bem.longitude }} ↗</a></dd></div>{% endif %}{% if entrega %}<div><dt>Devolução prevista</dt><dd>{{ entrega.previsao_retorno|datahora }}</dd></div>{% endif %}</dl></section>
<section class="panel"><h2>Histórico do bem</h2><div class="asset-timeline">{% for evento,autor in eventos %}<article><span></span><div><strong>{{ evento.acao }}</strong><p>{{ autor }} · {{ evento.criado_em|datahora }}</p><details><summary>Ver registro</summary><dl class="history-changes">{% for label,antes,depois in evento.mudancas %}<div><dt>{{ label }}</dt><dd>{{ antes }} → {{ depois }}</dd></div>{% else %}<p class="hint">Operação registrada no histórico do bem.</p>{% endfor %}</dl></details></div></article>{% else %}<p class="hint">Sem eventos registrados.</p>{% endfor %}</div></section>{% if bem.observacoes or bem.aquisicao_justificativa %}<section class="panel"><h2>Observações</h2><p class="detail-description">{{ bem.observacoes }}</p><p class="hint">{{ bem.aquisicao_justificativa }}</p></section>{% endif %}</div>
<aside class="asset-profile-aside">{% if not usuario.leitura %}<section class="panel"><h2>Plaqueta patrimonial</h2>{% if bem.numero_ngi or bem.plaqueta_original %}<div class="tag-preview"><img src="{{ url_for('qr_bem',bem_id=bem.id) }}" alt="QR Code da ficha do bem"><div><small>NGI ICMBio Carajás · Patrimônio</small><strong>{{ bem.numero_ngi or bem.plaqueta_original }}</strong>{% if bem.plaqueta_original %}<span>Plaqueta antiga: {{ bem.plaqueta_original }}{% if bem.origem %} · {{ bem.origem }}{% endif %}</span>{% endif %}{% if not bem.numero_ngi %}<span>Número ainda no formato antigo</span>{% endif %}</div></div><p class="hint">Modelo de 4 × 2,5 cm. O QR abre a ficha ou a conferência no celular.</p>{% if pode_acessar('imprimir_plaqueta') %}<a class="btn" href="{{ url_for('imprimir_plaqueta',bem_id=bem.id) }}">Visualizar impressão</a>{% endif %}{% else %}<p class="hint">Gere o número de patrimônio após conferir o cadastro.</p>{% endif %}{% if not bem.numero_ngi and not usuario.leitura and not bem.encerrado %}<p class="hint">{{ 'O número sai da plaqueta antiga (ex.: PA 010 vira 0010).' if bem.plaqueta_original else 'O sistema usa o próximo número da sequência de patrimônio.' }}</p><form method="post" action="{{ url_for('gerar_plaqueta',bem_id=bem.id) }}"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><button class="btn primary">Gerar número de patrimônio</button></form>{% endif %}</section>{% endif %}
{% if not usuario.leitura %}<section class="panel"><h2>Documentos do bem</h2><ul class="asset-documents">{% for d in documentos_bem %}<li><a class="content-link" href="{{ url_for('documento_detalhe',documento_id=d.id) }}">{{ d.tipo }}</a><small>DOC-{{ '%06d'|format(d.id) }} · {{ d.criado_em|datahora }}</small></li>{% else %}<li>Nenhum documento emitido.</li>{% endfor %}</ul>{% if not usuario.leitura and not bem.encerrado %}<a class="text-action" href="{{ url_for('documentos',aba='cadastro',bem_id=bem.id) }}">Emitir documento →</a>{% endif %}</section>
<section class="panel"><h2>Convênio e destinação</h2><p class="detail-description">{{ bem.convenio }}</p>{% if bem.convenio_id %}<a class="content-link" href="{{ url_for('encerramento_detalhe',convenio_id=bem.convenio_id) }}">Acompanhar destinação dos bens →</a>{% else %}<p class="hint">Vincule o cadastro ao convênio de origem para acompanhar seu encerramento.</p>{% endif %}{% if not usuario.leitura and not bem.encerrado %}<div class="op-actions"><a class="text-action" href="{{ url_for('baixas',aba='cadastro',bem_id=bem.id) }}">Solicitar encerramento / baixa</a></div>{% endif %}</section>{% endif %}</aside></div>
'''


LEITOR_QR_TEMPLATE = r"""
<div class="list-heading"><div><h1>Ler QR Code</h1><p>No celular, a leitura abre a conferência do inventário em andamento. No computador, abre a ficha.</p></div><a class="btn" href="{{ url_for('listar_bens') }}">Ver bens</a></div><section class="panel field27-start"><button class="btn primary" type="button" data-home-camera="general" id="qr-start">{{ icon('scan') }} Abrir câmera</button><p class="hint">Permita a câmera. Se não conseguir ler, digite a identificação abaixo.</p><form id="qr-manual" method="get" action="{{ url_for('listar_bens') if usuario.leitura else url_for('inventario_campo') }}"><div class="field"><label for="qr-code">Plaqueta, série ou conteúdo do QR Code</label><input id="qr-code" name="codigo" maxlength="500" required></div><button class="btn">Localizar bem</button></form></section><script>document.getElementById('qr-manual').addEventListener('submit',e=>{if(window.matchMedia('(max-width:768px)').matches&&{{ (not usuario.leitura)|tojson }})return;e.preventDefault();const code=document.getElementById('qr-code').value.trim();try{const u=new URL(code,location.origin);if([location.origin,new URL({{ PUBLIC_URL_MOBILE|tojson }}).origin].includes(u.origin)&&/^\/bem\/\d+\/?$/.test(u.pathname)){location.assign(u.pathname);return;}}catch(e){}location.assign({{ url_for('listar_bens')|tojson }}+'?q='+encodeURIComponent(code.slice(0,120)));});document.addEventListener('DOMContentLoaded',()=>{if(new URLSearchParams(location.search).get('camera')==='1')document.getElementById('qr-start').click();});</script>
"""

CONVENIOS_TEMPLATE = r"""
<div class="list-heading"><div><h1>Convênios e projetos</h1><p>Cadastre o custeio que será selecionado nos bens.</p></div></div>
{% include 'registro_navegacao' %}
{% if registro_erros %}<div class="erros" role="alert"><ul>{% for erro in registro_erros %}<li>{{ erro }}</li>{% endfor %}</ul></div>{% endif %}
<div class="registry-workspace">{% if not registro_formulario %}<section class="panel registry-list"><div class="panelhead"><div><h2>Convênios cadastrados</h2><p>{{ total_registros }} registros · 25 por página</p></div></div>{% include 'registro_filtros' %}<div class="tablewrap"><table><thead><tr><th>Convênio / projeto</th><th>Vigência</th><th>Situação</th><th>Ação</th></tr></thead><tbody>{% for c in registros %}<tr><td><strong>{{ c.nome }}</strong><small class="table-sub">{{ c.numero }}{% if c.financiador %} · {{ c.financiador }}{% endif %}{% if c.gestor %} · Gestor: {{ c.gestor }}{% endif %}{% if c.valor is not none %} · {{ c.valor|brl }}{% endif %}</small></td><td>{{ c.fim.strftime('%d/%m/%Y') if c.fim else 'Não informada' }}</td><td>{{ 'Ativo' if c.ativo else 'Inativo' }}</td><td>{% if not usuario.leitura %}<a class="text-action" href="{{ url_for('editar_convenio', convenio_id=c.id) }}">Editar</a>{% endif %}</td></tr>{% else %}<tr><td colspan="4">Nenhum convênio cadastrado.</td></tr>{% endfor %}</tbody></table></div>{% include 'registro_paginacao' %}</section>
{% else %}<section class="form-section registry-form"><h2>{{ 'Editar convênio' if convenio_editando else 'Novo convênio' }}</h2><form method="post" action="{{ url_for('editar_convenio',convenio_id=convenio_editando.id) if convenio_editando else url_for('convenios_cadastro') }}"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><input type="hidden" name="revisao" value="{{ registro_valores.get('revisao',convenio_editando.revisao if convenio_editando else 0) }}"><div class="fields">
{% for campo,label,limite in [('nome','Nome do convênio / projeto *',160),('numero','Número do instrumento',120),('financiador','Financiador / instituição',160),('gestor','Gestor do convênio',160)] %}<div class="field {{ 'wide' if campo == 'nome' }}"><label for="c-{{ campo }}">{{ label }}</label><input id="c-{{ campo }}" name="{{ campo }}" maxlength="{{ limite }}" {{ 'required' if campo == 'nome' }} value="{{ registro_valores.get(campo,'') }}"></div>{% endfor %}
<div class="field"><label for="c-valor">Valor do convênio (R$)</label><input id="c-valor" name="valor" inputmode="decimal" placeholder="Ex.: 1.250.000,00" value="{{ registro_valores.get('valor','') }}"></div>
<div class="field wide"><label for="c-objeto">Objeto / finalidade</label><textarea id="c-objeto" name="objeto" maxlength="3000">{{ registro_valores.get('objeto','') }}</textarea></div>
{% for campo,label in [('inicio','Início da vigência'),('fim','Fim da vigência')] %}<div class="field"><label for="c-{{ campo }}">{{ label }}</label><input id="c-{{ campo }}" type="date" name="{{ campo }}" value="{{ registro_valores.get(campo,'') }}"></div>{% endfor %}
{% if convenio_editando %}<div class="field wide"><label for="c-ativo">Disponibilidade</label><select id="c-ativo" name="ativo"><option value="sim" {{ 'selected' if registro_valores.get('ativo')=='sim' }}>Ativo</option><option value="nao" {{ 'selected' if registro_valores.get('ativo')=='nao' }}>Inativo</option></select></div>{% endif %}</div><div class="dialog-actions"><a class="btn" href="{{ url_for('convenios_cadastro') }}">Cancelar</a><button class="btn primary">Salvar convênio</button></div></form><small class="hint">Alterar o nome atualiza os bens vinculados e registra a mudança no histórico. Desativar preserva os vínculos existentes.</small></section>{% endif %}</div>
"""
USUARIOS_TEMPLATE = r"""
<div class="list-heading"><div><h1>Usuários</h1><p>Gerencie o acesso ao patrimônio. Somente administradores alteram contas.</p></div></div>
{% include 'registro_navegacao' %}
{% if registro_erros %}<div class="erros" role="alert"><ul>{% for erro in registro_erros %}<li>{{ erro }}</li>{% endfor %}</ul></div>{% endif %}
<div class="registry-workspace">{% if not registro_formulario %}<section class="panel registry-list"><div class="panelhead"><div><h2>Usuários cadastrados</h2><p>{{ total_registros }} registros · 25 por página</p></div></div>{% include 'registro_filtros' %}<div class="tablewrap"><table><thead><tr><th>Nome / e-mail</th><th>Perfil</th><th>Situação</th><th></th></tr></thead><tbody>{% for u in registros %}<tr><td><strong>{{ u.nome }}</strong><small class="table-sub">{{ u.email }}</small></td><td>{{ u.perfil }}{% if u.perfil=='Gestor de convênio' %}<small class="table-sub">{{ gestor_convenios_lista.get(u.id, [])|join(', ') or 'Sem convênio vinculado' }}</small>{% endif %}</td><td>{{ 'Ativo' if u.ativo else 'Inativo' }}</td><td><a class="text-action" href="{{ url_for('editar_usuario',usuario_id=u.id) }}">Editar</a>{% if u.ativo %}<form method="post" action="{{ url_for('enviar_link_usuario',usuario_id=u.id) }}" style="display:inline;margin-left:12px"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><button type="submit" class="btn" style="font-size:12px;min-height:38px">Enviar link de senha</button></form>{% endif %}</td></tr>{% else %}<tr><td colspan="4" class="list-empty">Nenhum usuário encontrado.</td></tr>{% endfor %}</tbody></table></div>{% include 'registro_paginacao' %}<div class="callout"><strong>Perfis de acesso</strong><p>Administrador: gerencia usuários e todo o patrimônio.<br>Operador: cadastra bens e cadastros auxiliares, movimenta, confere inventário, emite termos e gera plaquetas. Sem dashboards e exportações gerais.<br>Gestor de convênio: vê somente os bens, o encerramento e o relatório final dos convênios vinculados a ele. Sem alterações.<br>Consulta: página inicial, lista e ficha dos bens e guia. Sem alterações, sem plaquetas e sem acesso aos módulos operacionais.</p></div></section>
{% else %}<section class="form-section registry-form"><h2>{{ 'Editar usuário' if usuario_editando else 'Novo usuário' }}</h2><form method="post" action="{{ url_for('editar_usuario',usuario_id=usuario_editando.id) if usuario_editando else url_for('usuarios_cadastro') }}"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><input type="hidden" name="revisao" value="{{ registro_valores.get('revisao',usuario_editando.versao_sessao if usuario_editando else 0) }}"><div class="fields">
<div class="field"><label for="u-nome">Nome completo *</label><input id="u-nome" name="nome" maxlength="120" required value="{{ registro_valores.get('nome','') }}"></div><div class="field"><label for="u-email">E-mail *</label><input id="u-email" type="email" name="email" maxlength="254" required value="{{ registro_valores.get('email','') }}"></div>
<div class="field"><label for="u-perfil">Perfil *</label><select id="u-perfil" name="perfil">{% for perfil in perfis_usuario %}<option {{ 'selected' if registro_valores.get('perfil','Consulta')==perfil }}>{{ perfil }}</option>{% endfor %}</select></div>
<div class="field wide" id="u-convenios-campo"><label>Convênios que este gestor acompanha</label><div class="u-convenios">{% for c in convenios_todos %}<label class="u-conv"><input type="checkbox" name="convenio_ids" value="{{ c.id }}" {{ 'checked' if c.id in gestor_selecionados }}><span>{{ c.nome }}{{ ' · inativo' if not c.ativo }}</span></label>{% else %}<small>Cadastre os convênios primeiro.</small>{% endfor %}</div><small>Usado só no perfil Gestor de convênio: ele vê apenas os bens, o encerramento e o relatório final desses convênios.</small></div>
<script>(()=>{const p=document.getElementById('u-perfil'),c=document.getElementById('u-convenios-campo');function v(){c.hidden=p.value!=='Gestor de convênio';}p.addEventListener('change',v);v();})();</script><div class="field"><label for="u-ativo">Situação</label><select id="u-ativo" name="ativo"><option value="sim" {{ 'selected' if registro_valores.get('ativo','sim')=='sim' }}>Ativo</option><option value="nao" {{ 'selected' if registro_valores.get('ativo')=='nao' }}>Inativo</option></select></div>
<div class="field"><label for="u-senha">{{ 'Nova senha (opcional)' if usuario_editando else 'Senha inicial *' }}</label><input id="u-senha" type="password" name="senha" autocomplete="new-password" minlength="12" maxlength="128" {{ 'required' if not usuario_editando }}><small>De 12 a 128 caracteres. {% if usuario_editando %}Deixe vazio para manter a senha atual.{% endif %}</small></div><div class="field"><label for="u-confirmacao">Repita a senha</label><input id="u-confirmacao" type="password" name="confirmacao" autocomplete="new-password" maxlength="128" {{ 'required' if not usuario_editando }}></div></div><div class="dialog-actions"><a class="btn" href="{{ url_for('usuarios_cadastro') }}">Cancelar</a><button class="btn primary">Salvar usuário</button></div><small class="hint">O cadastro mantém a senha inicial definida aqui. Após salvar, use “Enviar link de senha” na lista para o usuário escolher sua própria senha. Uma alteração na conta encerra as sessões anteriores. Você não pode desativar ou reduzir o perfil da sua própria conta.</small></form></section>{% endif %}</div>
"""
GUIA_TEMPLATE = r"""
<div class="list-heading"><div><h1>Guia patrimonial</h1><p>Como cuidar dos bens dos projetos, do cadastro à saída, em linguagem simples.</p></div></div>
<section class="panel"><div class="guide-hub"><span>PATRIMÔNIO DOS PROJETOS E ACORDOS DE COOPERAÇÃO</span><h2>Gestão patrimonial</h2><p>Selecione um assunto para ver o conceito, como fazer no sistema, um exemplo e a base normativa.</p></div><div class="guide-map" role="tablist" aria-label="Assuntos patrimoniais">{% for t in topicos_guia %}<button type="button" class="guide-node" role="tab" id="guia-aba-{{ loop.index0 }}" aria-controls="guia-painel-{{ loop.index0 }}" data-guia="{{ loop.index0 }}" aria-selected="{{ 'true' if loop.first else 'false' }}" aria-pressed="{{ 'true' if loop.first else 'false' }}"><small>{{ '%02d'|format(loop.index) }}</small><strong>{{ t.titulo }}</strong><span>{{ t.resumo }}</span></button>{% endfor %}</div>
{% for t in topicos_guia %}<article class="guide-explanation" role="tabpanel" id="guia-painel-{{ loop.index0 }}" aria-labelledby="guia-aba-{{ loop.index0 }}"{{ '' if loop.first else ' hidden' }}><h2>{{ t.titulo }}</h2>
<div class="guide-block"><span>O que é</span><p>{{ t.texto }}</p></div>
<div class="guide-block pratica"><span>Como fazer no sistema</span><p>{{ t.pratica }}</p></div>
<div class="guide-block exemplo"><span>Exemplo</span><p>{{ t.exemplo }}</p></div>
{% if t.alerta %}<p class="guide-alert">{{ t.alerta }}</p>{% endif %}
<div class="guide-sources"><span>Base normativa</span>{% for rotulo,url in t.fontes %}<a href="{{ url }}" target="_blank" rel="noopener noreferrer">{{ rotulo }}</a>{% endfor %}</div></article>{% endfor %}</section>
<div class="callout"><strong>Como este guia funciona</strong><p>Os bens dos projetos e acordos de cooperação do NGI ICMBio Carajás seguem as boas práticas de controle da Administração Pública Federal, principalmente a IN SEDAP nº 205/1988: cada bem identificado, com responsável e termo, toda mudança registrada, inventário periódico e saída documentada. Ao fim de cada projeto, o destino dos bens segue o que o acordo de cooperação prevê.</p></div>
<script>
document.querySelectorAll('[data-guia]').forEach(botao=>botao.addEventListener('click',()=>{document.querySelectorAll('[data-guia]').forEach(b=>{const ativo=b===botao;b.setAttribute('aria-pressed',String(ativo));b.setAttribute('aria-selected',String(ativo));document.getElementById(b.getAttribute('aria-controls')).hidden=!ativo;});if(window.matchMedia('(max-width:700px)').matches){document.getElementById(botao.getAttribute('aria-controls')).scrollIntoView({behavior:'smooth',block:'start'});}}));
</script>
"""


VISAO_GERAL_TEMPLATE = '''{% if usuario.leitura %}'''+'<div class="list-heading"><div><h1>Consulta patrimonial</h1><p>Olá, {{ usuario.nome.split()[0] }}. Pesquise os bens e consulte suas informações.</p></div><a class="btn primary" href="{{ url_for(\'leitor_qr\') }}">{{ icon(\'scan\') }} Ler QR Code</a></div><section class="panel"><strong>{{ quantidade }} bens ativos no acervo</strong><p>{{ ("Gestor de convênio · " ~ (convenios_gestor_nomes|join(", ") or "nenhum convênio vinculado")) if usuario.perfil=="Gestor de convênio" else "Perfil Consulta" }} · acesso somente para leitura.</p></section><section class="panel home19-assets" id="home-assets"><div class="home19-section-title"><div><h2>Bens patrimoniais</h2><p>Consulte os bens ativos cadastrados no sistema.</p></div><a class="text-action" href="{{ url_for(\'listar_bens\') }}">Ver todos os bens →</a></div><form method="get" action="{{ url_for(\'inicio\') }}#home-assets" class="home19-filters"><div><label class="visually-hidden" for="home-q">Buscar bens</label><input id="home-q" type="search" name="q" maxlength="120" value="{{ home_busca }}" placeholder="Buscar por nome, série ou patrimônio…"></div><div><label class="visually-hidden" for="home-local">Local</label><select id="home-local" name="local"><option value="">Todos os locais</option>{% for l in locais %}<option {{ \'selected\' if home_local==l }}>{{ l }}</option>{% endfor %}</select></div><div><label class="visually-hidden" for="home-cat">Categoria</label><select id="home-cat" name="categoria_id"><option value="">Todas as categorias</option>{% for cat in categorias_home %}<option value="{{ cat.id }}" {{ \'selected\' if home_categoria==cat.id }}>{{ cat.nome }}</option>{% endfor %}</select></div><button class="btn primary">Filtrar</button>{% if home_busca or home_local or home_categoria %}<a class="text-action" href="{{ url_for(\'inicio\') }}#home-assets">Limpar</a>{% endif %}</form><div class="tablewrap"><table class="home19-table"><thead><tr><th>Bem</th><th>Patrimônio</th><th>Local</th><th>Convênio</th><th>Situação</th><th>Ações</th></tr></thead><tbody>{% for b in rows %}<tr><td><div class="home19-asset-name"><a class="home19-thumb" href="{{ url_for(\'ficha\',bem_id=b.id,consulta=1) }}" aria-label="Abrir ficha de {{ b.nome }}">{% if b.tem_foto %}<img loading="lazy" src="{{ url_for(\'foto_bem\',bem_id=b.id) }}" alt="Foto de {{ b.nome }}">{% else %}{{ icon(\'box\') }}{% endif %}</a><div><strong>{{ b.nome }}</strong><small>{{ b.marca or \'\' }} {{ b.modelo or \'\' }}</small></div></div></td><td>{{ b.numero_ngi or b.plaqueta_original or \'Sem identificação\' }}</td><td>{{ b.local }}</td><td>{{ b.convenio or \'Não identificado\' }}</td><td><span class="badge {{ \'warn\' if b.situacao not in [\'Em uso\',\'Armazenado\'] }}">{{ b.situacao }}</span></td><td><a class="text-action" href="{{ url_for(\'ficha\',bem_id=b.id,consulta=1) }}">Abrir ficha →</a></td></tr>{% else %}<tr><td colspan="6" class="list-empty">Nenhum bem encontrado. Ajuste os filtros ou cadastre o primeiro bem.</td></tr>{% endfor %}</tbody></table></div>{% include \'op_paginacao\' %}<p class="home19-scope">Os filtros acima se aplicam à lista. Os indicadores mostram todo o acervo ativo.</p></section>\n'+'''{% else %}'''+VISAO_GERAL_TEMPLATE+'''{% endif %}'''
app.jinja_loader = ChoiceLoader([DictLoader({"registro_navegacao": REGISTRO_NAVEGACAO_TEMPLATE, "registro_filtros": REGISTRO_FILTROS_TEMPLATE, "registro_paginacao": REGISTRO_PAGINACAO_TEMPLATE, "formulario": FORMULARIO_BEM, "cadastros": CADASTROS_TEMPLATE, "campos_base": CAMPOS_BASE_TEMPLATE, "lista_bens": LISTA_BENS_TEMPLATE, "ficha_compacta": FICHA_COMPACTA_TEMPLATE, "visao_geral": VISAO_GERAL_TEMPLATE, "leitor_qr": LEITOR_QR_TEMPLATE, "convenios_cadastro": CONVENIOS_TEMPLATE, "usuarios_cadastro": USUARIOS_TEMPLATE, "guia": GUIA_TEMPLATE}), app.jinja_loader])
SITUACOES = ("Em uso", "Disponível", "Em campo", "Manutenção")
CONSERVACOES = ("Bom", "Novo", "Regular", "Ruim", "Inservível")
# Regra do NGI ICMBio Carajás: bem permanente com valor igual ou superior a R$ 250,00 é patrimônio.
VALOR_MINIMO_PATRIMONIO = Decimal("250.00")
CLASSIFICACOES = ("Patrimônio", "Não é patrimônio")


def classificacao_sugerida(valor):
    return "Não é patrimônio" if valor is not None and valor < VALOR_MINIMO_PATRIMONIO else "Patrimônio"


# Bens próprios do ICMBio (patrimônio da União) não dependem de convênio.
# Internamente ficam ligados a um registro fixo, para aparecer em filtros e relatórios.
NOME_PATRIMONIO_UNIAO = "ICMBio · Patrimônio da União"


def convenio_uniao(criar=False):
    chave = NOME_PATRIMONIO_UNIAO.casefold()
    conv = db.session.scalar(select(Convenio).where(Convenio.nome_chave == chave))
    if conv is None and criar:
        try:
            with db.session.begin_nested():
                conv = Convenio(nome=NOME_PATRIMONIO_UNIAO, nome_chave=chave, financiador="União · ICMBio",
                                objeto="Bens próprios do ICMBio (patrimônio da União), sem vínculo com convênio.")
                db.session.add(conv)
        except IntegrityError:
            conv = db.session.scalar(select(Convenio).where(Convenio.nome_chave == chave))
    if conv is not None and criar and not conv.ativo:
        conv.ativo = True
    return conv


def eh_convenio_uniao(convenio):
    return convenio is not None and convenio.nome_chave == NOME_PATRIMONIO_UNIAO.casefold()


CAMPOS_TEXTO = {
    "nome": (160, True), "descricao": (5000, True),
    "marca": (100, True), "modelo": (120, True),
    "serie": (160, False), "serie_justificativa": (2000, False),
    "origem": (120, False), "plaqueta_original": (120, False),
    "convenio": (160, True), "local": (160, True), "endereco": (300, True),
    "complemento": (200, False), "responsavel": (160, True),
    "responsavel_contato": (160, False), "aquisicao_justificativa": (2000, False),
    "observacoes": (5000, False),
    "nota_fiscal": (60, False), "fornecedor": (160, False),
    "ingresso_detalhe": (200, False),
}
FORMAS_INGRESSO = ("Compra", "Doação", "Apreensão destinada ao NGI")
ROTULOS = {
    "nome": "Nome do bem", "descricao": "Descrição", "marca": "Marca",
    "modelo": "Modelo", "convenio": "Convênio / projeto", "local": "Nome do local",
    "endereco": "Endereço / referência", "responsavel": "Responsável",
    "nota_fiscal": "Nota fiscal", "fornecedor": "Fornecedor", "coordenacao": "Coordenação responsável",
    "classificacao": "Classificação patrimonial",
    "forma_ingresso": "Forma de entrada", "ingresso_detalhe": "Doador / processo de origem",
}


def ler_foto(arquivo):
    if not arquivo or not arquivo.filename:
        return None
    # Bibliotecas e validações anteriores podem ter lido o stream: reabra do início.
    arquivo.stream.seek(0)
    bruto = arquivo.read(10 * 1024 * 1024 + 1)
    if len(bruto) > 10 * 1024 * 1024:
        raise ValueError("A fotografia deve ter até 10 MB.")
    if not bruto:
        raise ValueError("A foto chegou vazia. Selecione o arquivo novamente antes de salvar.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(bruto)) as original:
                if original.format not in {"JPEG", "PNG", "WEBP", "HEIF", "AVIF"}:
                    raise ValueError("Envie uma fotografia JPEG, PNG, WebP, HEIC/HEIF ou AVIF.")
                if original.width * original.height > 50_000_000:
                    raise ValueError("A fotografia deve ter no máximo 50 megapixels.")
                original.seek(0)
                # Reduz JPEGs grandes durante a decodificação quando possível.
                original.draft("RGB", (1600, 1600))
                original.load()
                imagem = ImageOps.exif_transpose(original)
                imagem.thumbnail((1600, 1600))
                imagem = imagem.convert("RGBA")
                fundo = Image.new("RGB", imagem.size, "white")
                fundo.paste(imagem, mask=imagem.getchannel("A"))
                saida = io.BytesIO()
                fundo.save(saida, format="JPEG", quality=85, optimize=True)
                return saida.getvalue()
    except (UnidentifiedImageError, OSError, EOFError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError("Não foi possível decodificar a foto: o arquivo pode estar incompleto ou em um formato não suportado. Exporte como JPEG/PNG ou envie outra foto. HEIC/HEIF também é aceito.") from None


def validar_bem(formulario, registro=None):
    erros = []
    dados = {}
    for campo, (limite, obrigatorio) in CAMPOS_TEXTO.items():
        valor = formulario.get(campo, "").strip()
        if obrigatorio and campo not in {"local", "endereco", "convenio"} and not valor:
            erros.append(f"{ROTULOS.get(campo, campo)} é obrigatório.")
        if len(valor) > limite:
            erros.append(f"{ROTULOS.get(campo, campo)}: máximo de {limite} caracteres.")
        dados[campo] = valor
    dados["marca"] = dados["marca"].upper()
    forma_ingresso = formulario.get("forma_ingresso", "Compra").strip() or "Compra"
    if forma_ingresso not in FORMAS_INGRESSO:
        erros.append("Escolha a forma de entrada do bem: Compra, Doação ou Apreensão.")
        forma_ingresso = "Compra"
    if forma_ingresso == "Compra":
        dados["ingresso_detalhe"] = ""
    elif forma_ingresso == "Doação" and len(dados["ingresso_detalhe"]) < 2:
        erros.append("Informe quem doou o bem (ex.: Vale).")
    dados["forma_ingresso"] = forma_ingresso
    dados["serie"] = dados["serie"].upper() or None
    dados["origem"] = dados["origem"].upper() or None
    dados["plaqueta_original"] = dados["plaqueta_original"].upper() or None
    status_serie = formulario.get("serie_excecao", "Informado")
    if status_serie not in {"Informado", "Não possui", "Ilegível"}:
        erros.append("Escolha a situação do número de série.")
    if status_serie == "Informado":
        if not dados["serie"]:
            erros.append("Informe o número de série do bem.")
        dados["serie_justificativa"] = ""
    else:
        dados["serie"] = None
        if len(dados["serie_justificativa"]) < 10:
            erros.append(
                "Justifique a ausência ou ilegibilidade da série com pelo menos 10 caracteres."
            )
    dados["serie_excecao"] = status_serie
    dados["etiqueta_situacao"] = formulario.get(
        "etiqueta_situacao", registro.etiqueta_situacao if registro else "Não verificada"
    )
    if dados["etiqueta_situacao"] not in {
        "Não verificada",
        "Sem etiqueta",
        "Danificada",
        "Legível",
    }:
        erros.append("Escolha uma situação válida para a etiqueta física.")
    possui = formulario.get("possui_plaqueta", "nao")
    if registro and registro.numero_ngi:
        # Número já definido: a plaqueta antiga fica como está (histórico).
        dados.pop("origem", None)
        dados.pop("plaqueta_original", None)
    elif possui == "sim":
        if not dados["origem"] or not dados["plaqueta_original"]:
            erros.append("Informe o número e a origem da plaqueta original.")
        else:
            numero = numero_de_plaqueta(dados["plaqueta_original"])
            if not numero:
                erros.append("O número da plaqueta precisa ter algarismos (ex.: PA 010 vira o patrimônio 0010).")
            else:
                outro = db.session.scalar(select(Bem).where(Bem.numero_ngi == numero, Bem.id != (registro.id if registro else -1)).limit(1))
                if outro:
                    erros.append(f"O número de patrimônio {numero} (da plaqueta {dados['plaqueta_original']}) já pertence ao bem {outro.nome}. Confira a plaqueta.")
                else:
                    dados["numero_ngi"] = numero
    elif possui == "nao":
        dados["origem"] = None
        dados["plaqueta_original"] = None
    else:
        erros.append("Informe se o bem possui plaqueta.")
    for campo, opcoes in (("situacao", SITUACOES), ("conservacao", CONSERVACOES)):
        dados[campo] = formulario.get(campo, "")
        if dados[campo] not in opcoes:
            erros.append(f"Escolha uma opção válida para {campo}.")
    dados["data_aquisicao"] = None
    if formulario.get("data_aquisicao", "").strip():
        try:
            dados["data_aquisicao"] = date.fromisoformat(formulario["data_aquisicao"])
            if not date(1900, 1, 1) <= dados["data_aquisicao"] <= date.today():
                erros.append("A data de aquisição deve estar entre 1900 e hoje.")
        except ValueError:
            erros.append("Informe uma data de aquisição válida.")
    dados["valor"] = None
    texto_valor = re.sub(r"^R\$\s*", "", formulario.get("valor", "").strip(), flags=re.I).replace(" ", "")
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", texto_valor):
        texto_valor = texto_valor.replace(".", "")  # 1.500 = mil e quinhentos
    if texto_valor:
        try:
            if "," in texto_valor:
                if not re.fullmatch(r"(?:\d+|\d{1,3}(?:\.\d{3})+),\d{1,2}", texto_valor):
                    raise ValueError()
                normalizado = texto_valor.replace(".", "").replace(",", ".")
            else:
                if not re.fullmatch(r"\d+(?:\.\d{1,2})?", texto_valor):
                    raise ValueError()
                normalizado = texto_valor
            numero = Decimal(normalizado)
            if not numero.is_finite() or not Decimal("0") <= numero <= Decimal("999999999999.99"):
                raise ValueError()
            dados["valor"] = numero.quantize(Decimal("0.01"))
        except (ValueError, InvalidOperation):
            erros.append("Valor inválido. Use, por exemplo, 6.800,00 ou 6800,00.")
    # Quem cadastra escolhe Sim ou Não; o valor só serve de sugestão.
    classificacao = formulario.get("classificacao", "").strip()
    justificativa_classif = formulario.get("classificacao_justificativa", "").strip()[:2000]
    if not classificacao:
        erros.append("Informe se o item é patrimônio: escolha Sim ou Não.")
        classificacao = classificacao_sugerida(dados["valor"])
    elif classificacao not in CLASSIFICACOES:
        erros.append("Escolha se o item é ou não patrimônio.")
        classificacao = classificacao_sugerida(dados["valor"])
    elif classificacao != classificacao_sugerida(dados["valor"]) and len(justificativa_classif) < 10:
        erros.append("A classificação é diferente da regra dos R$ 250,00. Explique o motivo com pelo menos 10 caracteres.")
    if classificacao == classificacao_sugerida(dados["valor"]):
        justificativa_classif = ""
    dados.update(classificacao=classificacao, classificacao_justificativa=justificativa_classif)
    if (dados["valor"] is None or dados["data_aquisicao"] is None) and len(
        dados["aquisicao_justificativa"]
    ) < 10:
        erros.append(
            "Justifique com pelo menos 10 caracteres a data ou o valor de aquisição não informado."
        )
    for campo, limite in (("latitude", 90), ("longitude", 180)):
        dados[campo] = None
        valor = formulario.get(campo, "").strip()
        if valor:
            try:
                numero = Decimal(valor.replace(",", "."))
                if not numero.is_finite() or not -limite <= numero <= limite:
                    raise ValueError()
                dados[campo] = numero.quantize(Decimal("0.0000001"))
            except (ValueError, InvalidOperation):
                erros.append(f"Informe {campo} válida entre {-limite} e {limite}.")
    if (dados["latitude"] is None) != (dados["longitude"] is None):
        erros.append("Preencha latitude e longitude juntas, ou deixe ambas vazias.")
    try:
        base_id = int(formulario.get("base_id", ""))
    except (TypeError, ValueError):
        base_id = None
    base = db.session.get(BaseLocal, base_id) if base_id else None
    if base is None or (not base.ativo and (registro is None or registro.base_id != base.id)):
        erros.append(
            "Selecione uma base ou local ativo na lista. Use Nova base para cadastrar um local."
        )
    else:
        dados.update(
            base_id=base.id,
            local=base.nome,
            endereco=base.endereco,
            latitude=base.latitude,
            longitude=base.longitude,
        )
    try:
        convenio_id = int(formulario.get("convenio_id", ""))
    except (TypeError, ValueError):
        convenio_id = None
    convenio = db.session.get(Convenio, convenio_id) if convenio_id else None
    if formulario.get("origem_recurso") == "uniao":
        convenio = convenio_uniao(criar=True)
        dados.update(convenio_id=convenio.id, convenio=convenio.nome)
    elif convenio is None or (
        not convenio.ativo and (registro is None or registro.convenio_id != convenio.id)
    ):
        erros.append(
            "Selecione um convênio ativo cadastrado. Use Cadastros → Convênios para cadastrar."
        )
    else:
        dados.update(convenio_id=convenio.id, convenio=convenio.nome)
    categoria_id = inteiro(formulario.get('categoria_id'))
    categoria = db.session.get(Categoria, categoria_id) if categoria_id else None
    if categoria is None:
        dados.update(categoria_id=None, categoria='')
        if registro is None or registro.categoria_id or formulario.get('categoria_id'):
            erros.append(
                'Selecione uma categoria ativa na lista. Cadastre as categorias no menu Cadastros.'
            )
    elif not categoria.ativo and (registro is None or registro.categoria_id != categoria.id):
        dados.update(categoria_id=None, categoria='')
        erros.append('Esta categoria está inativa para novos vínculos.')
    else:
        dados.update(categoria_id=categoria.id, categoria=categoria.nome)
    coordenacao_id = inteiro(formulario.get('coordenacao_id'))
    coordenacao = db.session.get(Coordenacao, coordenacao_id) if coordenacao_id else None
    if not formulario.get('coordenacao_id'):
        dados.update(coordenacao_id=None, coordenacao='')
    elif coordenacao is None:
        dados.update(coordenacao_id=None, coordenacao='')
        erros.append('Selecione uma coordenação da lista. Cadastre as coordenações no menu Cadastros.')
    elif not coordenacao.ativo and (registro is None or registro.coordenacao_id != coordenacao.id):
        dados.update(coordenacao_id=None, coordenacao='')
        erros.append('Esta coordenação está inativa para novos vínculos.')
    else:
        dados.update(coordenacao_id=coordenacao.id, coordenacao=coordenacao.sigla)
    return dados, erros


def snapshot(bem):
    return {campo: str(getattr(bem, campo)) if getattr(bem, campo) is not None else None
            for campo in (*CAMPOS_TEXTO, "base_id", "convenio_id", "categoria_id", "categoria", "coordenacao_id", "coordenacao", "classificacao", "forma_ingresso", "serie_excecao", "numero_ngi", "situacao", "conservacao",
                          "data_aquisicao", "valor", "latitude", "longitude", "tem_foto", "etiqueta_situacao", "revisao", "encerrado", "encerrado_em", "conferido")}


def registrar_evento(bem, acao, antes=None):
    db.session.add(EventoBem(
        bem_id=bem.id, usuario_id=g.usuario.id, acao=acao,
        detalhes=json.dumps({"antes": antes, "depois": snapshot(bem)}, ensure_ascii=False),
    ))


def obter_bem(bem_id, bloquear=False):
    consulta = select(Bem).where(Bem.id == bem_id)
    if bloquear:
        consulta = consulta.with_for_update()
    bem = db.session.scalar(consulta)
    if bem is None or not bem_visivel(bem):
        abort(404)
    return bem


def mostrar_formulario(valores, erros, registro=None, token=None, status=200):
    token = token or secrets.token_hex(24)
    bases = db.session.scalars(select(BaseLocal).where(
        (BaseLocal.ativo == True) | (BaseLocal.id == (registro.base_id if registro else -1))
    ).order_by(BaseLocal.nome)).all()
    uniao = convenio_uniao()
    convenios_cadastrados = [c for c in db.session.scalars(select(Convenio).where(
        (Convenio.ativo == True) | (Convenio.id == (registro.convenio_id if registro else -1))
    ).order_by(Convenio.nome)).all() if not eh_convenio_uniao(c)]
    return render_template_string(
        TEMPLATE, bem=None, formulario=True, registro=registro, valores=valores,
        erros=erros, operacao_token=token, hoje=date.today().isoformat(),
        bases=bases, bases_json=[base_json(base) for base in bases],
        convenios_cadastrados=convenios_cadastrados, convenio_uniao_id=uniao.id if uniao else None, formas_ingresso=FORMAS_INGRESSO,
        categorias_cadastradas=db.session.scalars(select(Categoria).where((Categoria.ativo.is_(True)) | (Categoria.id==(registro.categoria_id if registro else -1))).order_by(Categoria.nome)).all(),
        classificacoes=CLASSIFICACOES,
        coordenacoes_cadastradas=db.session.scalars(select(Coordenacao).where((Coordenacao.ativo.is_(True)) | (Coordenacao.id==(registro.coordenacao_id if registro and registro.coordenacao_id else -1))).order_by(Coordenacao.sigla)).all(),
        situacoes=SITUACOES, conservacoes=CONSERVACOES,
        responsaveis=db.session.scalars(select(Bem.responsavel).distinct().order_by(Bem.responsavel)).all(),
        **contexto_painel(),
    ), status


def salvar_nota_fiscal(bem, arquivo, lido):
    """Grava ou substitui o arquivo opcional da nota fiscal do bem."""
    dados, mime, ext = lido
    base = re.sub(r'[^\w .()-]', '_', arquivo.filename.rsplit('/', 1)[-1].rsplit('\\', 1)[-1])[:140].rsplit('.', 1)[0]
    nota = db.session.get(NotaFiscalBem, bem.id)
    if nota is None:
        nota = NotaFiscalBem(bem_id=bem.id)
        db.session.add(nota)
    nota.nome = (base or 'Nota fiscal') + '.' + ext
    nota.mime = mime
    nota.dados = dados
    nota.sha256 = hashlib.sha256(dados).hexdigest()
    nota.autor_id = g.usuario.id
    nota.criado_em = datetime.now(timezone.utc)


def ler_nota_fiscal_formulario(erros):
    """Lê o arquivo opcional da nota fiscal; sem arquivo, devolve (None, None)."""
    arquivo = request.files.get("nota_fiscal_arquivo")
    if not arquivo or not arquivo.filename:
        return None, None
    try:
        return arquivo, ler_arquivo_documento(arquivo)
    except ValueError as erro:
        erros.append("Nota fiscal: " + str(erro))
        return arquivo, None


@app.get("/bem/<int:bem_id>/nota-fiscal")
@login_obrigatorio
def nota_fiscal_bem(bem_id):
    nota = db.session.get(NotaFiscalBem, bem_id)
    dono = db.session.get(Bem, bem_id)
    if nota is None or dono is None or not bem_visivel(dono):
        abort(404)
    return Response(nota.dados, mimetype=nota.mime,
                    headers={"Content-Disposition": "inline; filename*=UTF-8''" + quote(nota.nome)})


@app.route("/bens/novo", methods=["GET", "POST"])
@login_obrigatorio
def cadastrar_bem():
    if request.method == "GET":
        token = secrets.token_hex(24)
        tokens = session.get("cadastros_tokens", [])[-9:]
        session["cadastros_tokens"] = tokens + [token]
        valores = {}
        if request.args.get("entrada"):
            entrada = db.session.get(EntradaSigad, inteiro(request.args.get("entrada")) or -1)
            if entrada is None:
                abort(404)
            if entrada.status != 'Aguardando tombamento':
                flash("Esta entrada do SIGAD já foi tratada.")
                return redirect(url_for("entradas_sigad"))
            valores = valores_entrada_sigad(entrada)
        return mostrar_formulario(valores, [], token=token)
    token = request.form.get("operacao_token", "")
    anterior = db.session.get(OperacaoCadastro, token)
    if anterior and anterior.usuario_id == g.usuario.id:
        return redirect(url_for("listar_bens", destacar=anterior.bem_id))
    if token not in session.get("cadastros_tokens", []):
        flash("Formulário antigo ou já utilizado. Abra um novo cadastro.")
        return redirect(url_for("cadastrar_bem"))
    dados, erros = validar_bem(request.form)
    entrada = None
    if request.form.get("entrada_sigad_id"):
        entrada = db.session.get(EntradaSigad, inteiro(request.form.get("entrada_sigad_id")) or -1)
        if entrada is None or entrada.status != 'Aguardando tombamento':
            erros.append("Esta entrada do SIGAD já foi tombada ou descartada por outra pessoa. Confira a lista de entradas.")
    foto = None
    try:
        foto = ler_foto(request.files.get("foto"))
    except ValueError as erro:
        erros.append(str(erro))
    nota_arquivo, nota_lida = ler_nota_fiscal_formulario(erros)
    if erros:
        if request.files.get("foto") and request.files["foto"].filename:
            erros.append("Selecione novamente a foto antes de reenviar.")
        if nota_arquivo:
            erros.append("Selecione novamente o arquivo da nota fiscal antes de reenviar.")
        return mostrar_formulario(request.form, erros, token=token, status=422)
    try:
        bem = Bem(**dados, criado_por=g.usuario.id, tem_foto=foto is not None)
        db.session.add(bem)
        db.session.flush()
        if foto is not None:
            db.session.add(FotoBem(bem_id=bem.id, dados=foto))
        if nota_lida is not None:
            salvar_nota_fiscal(bem, nota_arquivo, nota_lida)
        if entrada is not None:
            entrada = carregar(EntradaSigad, entrada.id, True)
            if entrada.status != 'Aguardando tombamento':
                db.session.rollback()
                return mostrar_formulario(request.form, ["Esta entrada do SIGAD acabou de ser tratada por outra pessoa. Confira a lista de entradas."], token=token, status=409)
            if nota_lida is None:
                copiar_nota_entrada_sigad(bem, entrada)
            entrada.status = 'Tombado'
            entrada.bem_id = bem.id
            entrada.tratado_por = g.usuario.id
            entrada.tratado_em = datetime.now(timezone.utc)
            registrar_evento(bem, "Cadastro do bem · compra do SIGAD")
        else:
            registrar_evento(bem, "Cadastro do bem")
        db.session.add(OperacaoCadastro(token=token, usuario_id=g.usuario.id, bem_id=bem.id))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        anterior = db.session.get(OperacaoCadastro, token)
        if anterior and anterior.usuario_id == g.usuario.id:
            return redirect(url_for("listar_bens", destacar=anterior.bem_id))
        return mostrar_formulario(request.form, ["Já existe um bem com essa marca e série ou com essa plaqueta e origem. Confira os registros. Se havia foto, selecione-a novamente."], token=token, status=409)
    if entrada is not None:
        restam = db.session.scalar(select(func.count(EntradaSigad.id)).where(EntradaSigad.status == 'Aguardando tombamento')) or 0
        flash("Bem tombado com sucesso." + (f" Ainda há {restam} entrada(s) do SIGAD aguardando tombamento." if restam else ""))
        return redirect(url_for("ficha", bem_id=bem.id))
    flash("Bem cadastrado com sucesso.")
    return redirect(url_for("listar_bens", destacar=bem.id))


@app.get("/bem/<int:bem_id>")
@login_obrigatorio
def ficha(bem_id):
    bem = obter_bem(bem_id)
    eventos = db.session.execute(
        select(EventoBem, Usuario.nome)
        .join(Usuario, EventoBem.usuario_id == Usuario.id)
        .where(EventoBem.bem_id == bem_id)
        .order_by(EventoBem.id.desc())
        .limit(30)
    ).all()
    documentos = db.session.scalars(
        select(Documento).where(documentos_do_bem([bem.id])).order_by(Documento.id.desc()).limit(12)
    ).all()
    item = db.session.scalar(
        select(ItemInventario)
        .join(CampanhaInventario)
        .where(ItemInventario.bem_id == bem.id, CampanhaInventario.status == 'Aberto')
        .limit(1)
    )
    rotulos = dict(
        ROTULOS,
        etiqueta_situacao='Etiqueta física',
        numero_ngi='Número de patrimônio',
        categoria='Categoria',
        local='Local',
        responsavel_contato='Contato',
        complemento='Sala / complemento',
        situacao='Situação',
        conservacao='Conservação',
        valor='Valor de aquisição',
        serie='Número de série',
        destino='Destinação',
        referencia='Referência',
        justificativa='Justificativa',
        status='Resultado',
        observacao='Observações',
        conferente='Conferente',
    )
    for evento, autor in eventos:
        evento.mudancas = []
        try:
            dados = json.loads(evento.detalhes)
            antes = dados.get('antes') or {}
            depois = dados.get('depois') or {}
            for campo, label in rotulos.items():
                if campo in depois and antes.get(campo) != depois[campo]:
                    evento.mudancas.append(
                        (label, str(antes.get(campo) or '—'), str(depois[campo] or '—'))
                    )
        except (ValueError, TypeError, AttributeError):
            pass
    return render_template_string(
        TEMPLATE,
        bem=bem,
        formulario=False,
        eventos=eventos,
        documentos_bem=documentos,
        entrega=entrega_aberta(bem.id),
        item_campanha=item,
        hoje_ficha=hoje_local(),
        **contexto_painel()
    )


@app.route("/bem/<int:bem_id>/editar", methods=["GET", "POST"])
@login_obrigatorio
def editar_bem(bem_id):
    bem = obter_bem(bem_id, bloquear=request.method == "POST")
    if bem.encerrado:
        flash("Este bem está baixado. O cadastro está preservado para consulta.")
        return redirect(url_for("ficha", bem_id=bem.id))
    if request.method == "GET":
        valores = {campo: getattr(bem, campo) or "" for campo in CAMPOS_TEXTO}
        valores.update(
            etiqueta_situacao=bem.etiqueta_situacao, serie_excecao=bem.serie_excecao, possui_plaqueta="sim" if bem.plaqueta_original else "nao",
            situacao=bem.situacao, conservacao=bem.conservacao,
            data_aquisicao=bem.data_aquisicao.isoformat() if bem.data_aquisicao else "",
            valor=str(bem.valor).replace(".", ",") if bem.valor is not None else "",
            latitude=str(bem.latitude) if bem.latitude is not None else "",
            longitude=str(bem.longitude) if bem.longitude is not None else "",
            revisao=bem.revisao, base_id=bem.base_id or "", convenio_id=bem.convenio_id or "", categoria_id=bem.categoria_id or "", coordenacao_id=bem.coordenacao_id or "", classificacao=bem.classificacao, classificacao_justificativa=bem.classificacao_justificativa,
            forma_ingresso=bem.forma_ingresso or "Compra",
        )
        return mostrar_formulario(valores, [], registro=bem)
    if request.form.get("revisao") != str(bem.revisao):
        db.session.rollback()
        flash("Este bem foi atualizado em outra tela. Reabra a edição e confira a versão atual.")
        return redirect(url_for("ficha", bem_id=bem_id))
    dados, erros = validar_bem(request.form, bem)
    if any(str(dados.get(campo) or '') != str(getattr(bem,campo) or '') for campo in ('base_id','local','endereco','complemento','responsavel','responsavel_contato')):
        erros.append('Para alterar local, sala ou responsável, use Movimentações na ficha do bem. Isso preserva a entrega e seu termo.')
    foto = None
    try:
        foto = ler_foto(request.files.get("foto"))
    except ValueError as erro:
        erros.append(str(erro))
    nota_arquivo, nota_lida = ler_nota_fiscal_formulario(erros)
    if erros:
        db.session.rollback()
        if request.files.get("foto") and request.files["foto"].filename:
            erros.append("Selecione novamente a foto antes de reenviar.")
        if nota_arquivo:
            erros.append("Selecione novamente o arquivo da nota fiscal antes de reenviar.")
        return mostrar_formulario(request.form, erros, registro=bem, status=422)
    antes = snapshot(bem)
    for campo, valor in dados.items():
        setattr(bem, campo, valor)
    atual = db.session.get(FotoBem, bem.id) if foto is not None or request.form.get("remover_foto") else None
    if foto is not None:
        if atual:
            atual.dados = foto
        else:
            db.session.add(FotoBem(bem_id=bem.id, dados=foto))
        bem.tem_foto = True
    elif request.form.get("remover_foto") == "sim":
        if atual:
            db.session.delete(atual)
        bem.tem_foto = False
    if nota_lida is not None:
        salvar_nota_fiscal(bem, nota_arquivo, nota_lida)
    bem.revisao += 1
    bem.atualizado_em = datetime.now(timezone.utc)
    bem.conferido = False
    registrar_evento(bem, "Edição do cadastro", antes)
    if nota_lida is not None:
        registrar_evento(bem, "Arquivo da nota fiscal anexado")
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return mostrar_formulario(request.form, ["Marca e série ou plaqueta e origem já cadastradas em outro bem. Se havia foto, selecione-a novamente."], registro=bem, status=409)
    flash("Cadastro atualizado com sucesso.")
    return redirect(url_for("listar_bens", q=bem.serie or bem.nome, destacar=bem.id))


@app.get("/bem/<int:bem_id>/foto")
@login_obrigatorio
def foto_bem(bem_id):
    foto = db.session.get(FotoBem, bem_id)
    dono = db.session.get(Bem, bem_id)
    if foto is None or dono is None or not bem_visivel(dono):
        abort(404)
    return Response(foto.dados, mimetype=foto.mime, headers={"Content-Disposition": "inline; filename=bem.jpg"})


# ---------- Número de patrimônio: sequência única de 4 dígitos ----------
# Plaqueta antiga "PA 010" vira o número 0010 (só os algarismos). Bens sem
# plaqueta recebem o próximo número depois do maior já usado. O número fica
# em Bem.numero_ngi; a plaqueta antiga continua guardada como histórico.
CHAVE_TRAVA_NUMERACAO = 739299999


def formatar_patrimonio(numero):
    return f'{int(numero):04d}'


def numero_de_plaqueta(valor):
    algarismos = re.sub(r'\D', '', valor or '')
    if not algarismos:
        return None
    return formatar_patrimonio(int(algarismos))


def travar_numeracao():
    if db.engine.dialect.name == 'postgresql':
        db.session.execute(text('SELECT pg_advisory_xact_lock(:chave)'), {'chave': CHAVE_TRAVA_NUMERACAO})


def maior_numero_patrimonio():
    maior = 0
    for valor in db.session.scalars(select(Bem.numero_ngi).where(Bem.numero_ngi.is_not(None))):
        if valor and valor.isdigit():
            maior = max(maior, int(valor))
    # plaquetas antigas ainda não convertidas também reservam o seu número
    for valor in db.session.scalars(select(Bem.plaqueta_original).where(
            Bem.numero_ngi.is_(None), Bem.plaqueta_original.is_not(None))):
        n = numero_de_plaqueta(valor)
        if n:
            maior = max(maior, int(n))
    return maior


def numero_ocupado(numero, bem_id=None):
    consulta = select(Bem.id).where(Bem.numero_ngi == numero)
    if bem_id:
        consulta = consulta.where(Bem.id != bem_id)
    return db.session.scalar(consulta.limit(1)) is not None


@app.template_filter('num_patrimonio')
def filtro_num_patrimonio(valor):
    if valor and str(valor).isdigit():
        return formatar_patrimonio(valor)
    return valor


@app.post("/bem/<int:bem_id>/gerar-plaqueta")
@login_obrigatorio
def gerar_plaqueta(bem_id):
    bem = obter_bem(bem_id, bloquear=True)
    if bem.encerrado:
        flash("Bens baixados não recebem nova numeração.")
        return redirect(url_for("ficha", bem_id=bem.id))
    voltar = url_for("listar_bens", destacar=bem_id) if request.form.get("voltar_lista") == "sim" else url_for("ficha", bem_id=bem_id)
    if bem.numero_ngi:
        db.session.rollback()
        flash(f"Este bem já tem o número de patrimônio {bem.numero_ngi}. O número não muda.")
        return redirect(voltar)
    antes = snapshot(bem)
    travar_numeracao()
    do_antigo = numero_de_plaqueta(bem.plaqueta_original)
    if do_antigo and not numero_ocupado(do_antigo, bem.id):
        codigo = do_antigo
    else:
        codigo = formatar_patrimonio(maior_numero_patrimonio() + 1)
    bem.numero_ngi = codigo
    bem.conferido = False
    bem.revisao += 1
    bem.atualizado_em = datetime.now(timezone.utc)
    registrar_evento(bem, "Número de patrimônio definido", antes)
    db.session.commit()
    flash(f"Número de patrimônio {bem.numero_ngi} gerado e salvo.")
    return redirect(url_for("listar_bens", destacar=bem.id) if request.form.get("voltar_lista") == "sim" else url_for("ficha", bem_id=bem.id))


@app.errorhandler(413)
def arquivo_grande(erro):
    return "O envio ultrapassou 12 MB. Volte ao formulário: fotos de bens aceitam até 10 MB; anexos de documentos, até 5 MB.", 413




# ============================================================
# CADASTROS DE BASES E LOCAIS
# ============================================================
def base_json(base):
    return dict(id=base.id, nome=base.nome, endereco=base.endereco,
                latitude=str(base.latitude), longitude=str(base.longitude), ativo=base.ativo)


def validar_base(valores):
    erros = []
    nome = " ".join(valores.get("nome", "").split())
    endereco = valores.get("endereco", "").strip()
    if not 2 <= len(nome) <= 160:
        erros.append("Informe um nome de local com 2 a 160 caracteres.")
    if not 3 <= len(endereco) <= 300:
        erros.append("Informe endereço ou referência física com 3 a 300 caracteres.")
    dados = dict(nome=nome, nome_chave=nome.casefold(), endereco=endereco)
    for campo, limite in (("latitude", 90), ("longitude", 180)):
        try:
            numero = Decimal(valores.get(campo, "").strip().replace(",", "."))
            if not numero.is_finite() or not -limite <= numero <= limite:
                raise ValueError()
            dados[campo] = numero.quantize(Decimal("0.0000001"))
        except (ValueError, InvalidOperation, AttributeError):
            erros.append(f"Informe {campo} válida entre {-limite} e {limite}.")
    return dados, erros


def contexto_registro(tipo, valores=None, erros=None, registro=None):
    configuracoes = {
        "locais": ("cadastros", "Bases cadastradas", "Cadastrar base", "Nome ou endereço"),
        "convenios": ("convenios_cadastro", "Convênios cadastrados", "Cadastrar convênio", "Nome, número ou financiador"),
        "categorias": ("categorias_cadastro", "Categorias cadastradas", "Cadastrar categoria", "Nome ou descrição"),
        "coordenacoes": ("coordenacoes_cadastro", "Coordenações cadastradas", "Cadastrar coordenação", "Sigla ou nome"),
        "usuarios": ("usuarios_cadastro", "Usuários cadastrados", "Cadastrar usuário", "Nome ou e-mail"),
    }
    endpoint, lista, novo, placeholder = configuracoes[tipo]
    formulario = registro is not None or valores is not None or bool(erros) or request.args.get("aba") == "cadastro"
    if formulario and g.usuario.leitura:
        abort(403)
    return dict(registro_endpoint=endpoint, registro_rotulo_lista=lista,
        registro_rotulo_novo=novo, registro_placeholder=placeholder,
        registro_formulario=formulario, registro_editando=registro is not None)


def tela_cadastros(valores=None, erros=None, registro=None, status=200):
    contexto = contexto_registro("locais", valores, erros, registro)
    paginacao = pagina_registros(BaseLocal, BaseLocal.nome, formulario=contexto["registro_formulario"])
    return render_template_string(
        TEMPLATE, cadastros_page=True, formulario=False, bem=None,
        base_valores=valores or {}, base_erros=erros or [], base_editando=registro,
        cadastro_tipo="locais", cadastro_titulo="Bases e locais",
        bases_registro=paginacao["registros"], **paginacao, **contexto, **contexto_painel(),
    ), status


@app.route("/cadastros", methods=["GET", "POST"])
@login_obrigatorio
def cadastros():
    if request.method == "GET":
        return tela_cadastros()
    dados, erros = validar_base(request.form)
    resposta_json = request.headers.get("Accept") == "application/json"
    if erros:
        if resposta_json:
            return jsonify(erros=erros), 422
        return tela_cadastros(request.form, erros, status=422)
    base = BaseLocal(**dados)
    try:
        db.session.add(base)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        erros = ["Já existe uma base com esse nome. Escolha-a na lista ou use um nome diferente."]
        if resposta_json:
            return jsonify(erros=erros), 409
        return tela_cadastros(request.form, erros, status=409)
    if resposta_json:
        return jsonify(base=base_json(base)), 201
    flash("Base cadastrada. Ela já está disponível na lista do cadastro de bens.")
    return redirect(url_for("cadastros"))


@app.route("/cadastros/bases/<int:base_id>/editar", methods=["GET", "POST"])
@login_obrigatorio
def editar_base(base_id):
    consulta = select(BaseLocal).where(BaseLocal.id == base_id)
    if request.method == "POST":
        consulta = consulta.with_for_update()
    base = db.session.scalar(consulta)
    if base is None:
        abort(404)
    if request.method == "GET":
        valores = base_json(base)
        valores.update(ativo="sim" if base.ativo else "nao", revisao=base.revisao)
        return tela_cadastros(valores, registro=base)
    if request.form.get("revisao") != str(base.revisao):
        db.session.rollback()
        flash("Este local foi atualizado em outra tela. Confira os dados e reabra a edição.")
        return redirect(url_for("editar_base", base_id=base_id))
    dados, erros = validar_base(request.form)
    if request.form.get("ativo") not in {"sim", "nao"}:
        erros.append("Selecione se a base está ativa ou inativa.")
    if erros:
        db.session.rollback()
        return tela_cadastros(request.form, erros, registro=base, status=422)
    mudou_localizacao = any(str(getattr(base, campo)) != str(dados[campo]) for campo in ("nome", "endereco", "latitude", "longitude"))
    # Lock assets in deterministic order before updating their location snapshot.
    bens = db.session.scalars(select(Bem).where(Bem.base_id == base_id).order_by(Bem.id).with_for_update()).all() if mudou_localizacao else []
    for bem in bens:
        antes = snapshot(bem)
        bem.local = dados["nome"]
        bem.endereco = dados["endereco"]
        bem.latitude = dados["latitude"]
        bem.longitude = dados["longitude"]
        bem.revisao += 1
        bem.atualizado_em = datetime.now(timezone.utc)
        bem.conferido = False
        registrar_evento(bem, "Atualização do cadastro do local", antes)
    for campo, valor in dados.items():
        setattr(base, campo, valor)
    base.ativo = request.form.get("ativo") == "sim"
    base.revisao += 1
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return tela_cadastros(request.form, ["Já existe outro local com esse nome."], registro=base, status=409)
    flash("Cadastro do local atualizado.")
    return redirect(url_for("cadastros"))


@app.get("/ler-qr")
@login_obrigatorio
def leitor_qr():
    return render_template_string(TEMPLATE, bem=None, formulario=False,
                                  leitor_page=True, **contexto_painel())


# ============================================================
# CONVÊNIOS, USUÁRIOS E GUIA PATRIMONIAL
# ============================================================
def pagina_registros(modelo, ordenacao, formulario=False):
    busca = request.args.get("q", "").strip()[:120]
    situacao = request.args.get("situacao", "")
    if situacao not in {"ativos", "inativos"}:
        situacao = ""
    filtros = []
    if busca:
        campos = [modelo.nome]
        if modelo is BaseLocal:
            campos.append(BaseLocal.endereco)
        elif modelo is Convenio:
            campos.extend([Convenio.numero, Convenio.financiador])
        elif modelo is Usuario:
            campos.append(Usuario.email)
        elif modelo is Coordenacao:
            campos.append(Coordenacao.sigla)
        else:
            campos.append(Categoria.descricao)
        filtros.append(or_(*(campo.icontains(busca, autoescape=True) for campo in campos)))
    if situacao:
        filtros.append(modelo.ativo == (situacao == "ativos"))
    total = 0 if formulario else (db.session.scalar(select(func.count()).select_from(modelo).where(*filtros)) or 0)
    paginas = max(1, (total + 24) // 25)
    try:
        pagina = max(1, min(int(request.args.get("pagina", "1")), paginas))
    except (TypeError, ValueError):
        pagina = 1
    registros = [] if formulario else db.session.scalars(select(modelo).where(*filtros).order_by(ordenacao, modelo.id).limit(25).offset((pagina-1)*25)).all()
    numeros = sorted({1, paginas, *range(max(1,pagina-2), min(paginas,pagina+2)+1)})
    return dict(registros=registros, total_registros=total, pagina_registro=pagina,
        paginas_registro=paginas, numeros_registro=numeros, registro_busca=busca,
        registro_situacao=situacao, primeiro_registro=(pagina-1)*25+1 if total else 0,
        ultimo_registro=min(pagina*25,total))


def tela_registro(tipo, valores=None, erros=None, registro=None, status=200):
    contexto = contexto_registro(tipo, valores, erros, registro)
    dados = dict(cadastros_page=True, formulario=False, bem=None,
        cadastro_tipo=tipo, cadastro_titulo="Usuários" if tipo=="usuarios" else "Convênios",
        registro_valores=valores or {}, registro_erros=erros or [],
        usuario_editando=registro if tipo=="usuarios" else None,
        convenio_editando=registro if tipo=="convenios" else None)
    modelo = Usuario if tipo=="usuarios" else Convenio
    if tipo == "usuarios":
        selecionados = set()
        if hasattr(valores, "getlist"):
            selecionados = {inteiro(x) for x in valores.getlist("convenio_ids") if inteiro(x)}
        elif registro is not None:
            selecionados = set(db.session.scalars(select(GestorConvenio.convenio_id).where(GestorConvenio.usuario_id == registro.id)))
        lista = {}
        for uid, nome in db.session.execute(select(GestorConvenio.usuario_id, Convenio.nome).join(Convenio, Convenio.id == GestorConvenio.convenio_id).order_by(Convenio.nome)):
            lista.setdefault(uid, []).append(nome)
        dados.update(perfis_usuario=PERFIS, convenios_todos=db.session.scalars(select(Convenio).order_by(Convenio.nome)).all(),
                     gestor_selecionados=selecionados, gestor_convenios_lista=lista)
    return render_template_string(TEMPLATE, **dados,
        **pagina_registros(modelo, modelo.nome, formulario=contexto["registro_formulario"]),
        **contexto, **contexto_painel()), status


def ler_valor_brl(texto):
    """Converte '1.250.000,00', '6800,00' ou '6800.00' em Decimal; ValueError se inválido."""
    texto = texto.strip()
    if "," in texto:
        if not re.fullmatch(r"(?:\d+|\d{1,3}(?:\.\d{3})+),\d{1,2}", texto):
            raise ValueError()
        texto = texto.replace(".", "").replace(",", ".")
    elif not re.fullmatch(r"\d+(?:\.\d{1,2})?", texto):
        raise ValueError()
    numero = Decimal(texto)
    if not numero.is_finite() or not Decimal("0") <= numero <= Decimal("999999999999.99"):
        raise ValueError()
    return numero.quantize(Decimal("0.01"))


def valor_brl_campo(valor):
    """Decimal -> '1.250.000,00' para preencher o formulário."""
    if valor is None:
        return ""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def validar_convenio(valores):
    erros = []
    dados = {}
    for campo, limite in (("nome",160),("numero",120),("financiador",160),("gestor",160),("objeto",3000)):
        dados[campo] = " ".join(valores.get(campo, "").split()) if campo=="nome" else valores.get(campo, "").strip()
        if len(dados[campo]) > limite or (campo=="nome" and len(dados[campo])<2):
            erros.append(f"Confira {campo}: máximo de {limite} caracteres; nome deve ter pelo menos 2.")
    dados["valor"] = None
    if valores.get("valor", "").strip():
        try:
            dados["valor"] = ler_valor_brl(valores.get("valor", ""))
        except (ValueError, InvalidOperation):
            erros.append("Valor do convênio inválido. Use, por exemplo, 1.250.000,00.")
    dados["nome_chave"] = dados["nome"].casefold()
    for campo in ("inicio","fim"):
        dados[campo] = None
        if valores.get(campo):
            try:
                dados[campo] = date.fromisoformat(valores[campo])
            except ValueError:
                erros.append(f"Data de {campo} inválida.")
    if dados["inicio"] and dados["fim"] and dados["inicio"] > dados["fim"]:
        erros.append("A vigência final deve ser igual ou posterior à inicial.")
    return dados, erros


@app.route("/cadastros/convenios", methods=["GET","POST"])
@login_obrigatorio
def convenios_cadastro():
    if request.method=="GET":
        return tela_registro("convenios")
    dados, erros = validar_convenio(request.form)
    if erros:
        return tela_registro("convenios", request.form, erros, status=422)
    try:
        db.session.add(Convenio(**dados))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return tela_registro("convenios", request.form, ["Já existe um convênio com esse nome."], status=409)
    flash("Convênio cadastrado. Ele já pode ser selecionado no cadastro de bens.")
    return redirect(url_for("convenios_cadastro"))


@app.route("/cadastros/convenios/<int:convenio_id>/editar", methods=["GET","POST"])
@login_obrigatorio
def editar_convenio(convenio_id):
    consulta = select(Convenio).where(Convenio.id==convenio_id)
    if request.method=="POST":
        consulta=consulta.with_for_update()
    convenio=db.session.scalar(consulta)
    if convenio is None:
        abort(404)
    if eh_convenio_uniao(convenio):
        flash("Este registro é do sistema: reúne os bens do ICMBio (patrimônio da União) e não pode ser alterado.")
        return redirect(url_for("convenios_cadastro"))
    if request.method=="GET":
        valores={c:getattr(convenio,c) or "" for c in ("nome","numero","financiador","gestor","objeto")}
        valores["valor"]=valor_brl_campo(convenio.valor)
        valores.update(inicio=convenio.inicio.isoformat() if convenio.inicio else "",
            fim=convenio.fim.isoformat() if convenio.fim else "", ativo="sim" if convenio.ativo else "nao", revisao=convenio.revisao)
        return tela_registro("convenios",valores,registro=convenio)
    dados,erros=validar_convenio(request.form)
    if request.form.get("revisao")!=str(convenio.revisao):
        erros.append("Este convênio foi atualizado em outra tela. Reabra a edição.")
    if request.form.get("ativo") not in {"sim","nao"}:
        erros.append("Informe se o convênio está ativo.")
    if erros:
        db.session.rollback()
        return tela_registro("convenios",request.form,erros,registro=convenio,status=409)
    if dados["nome"]!=convenio.nome:
        for bem in db.session.scalars(select(Bem).where(Bem.convenio_id==convenio_id).order_by(Bem.id).with_for_update()).all():
            antes=snapshot(bem)
            bem.convenio=dados["nome"]
            bem.revisao+=1
            bem.atualizado_em=datetime.now(timezone.utc)
            registrar_evento(bem,"Atualização do cadastro do convênio",antes)
    for campo,valor in dados.items():
        setattr(convenio,campo,valor)
    convenio.ativo=request.form.get("ativo")=="sim"
    convenio.revisao+=1
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return tela_registro("convenios",request.form,["Já existe outro convênio com esse nome."],registro=convenio,status=409)
    flash("Convênio atualizado.")
    return redirect(url_for("convenios_cadastro"))


def validar_usuario(valores, registro=None):
    nome=" ".join(valores.get("nome","").split())
    email=valores.get("email","").strip().casefold()
    perfil=valores.get("perfil","Consulta")
    ativo=valores.get("ativo","sim")
    senha=valores.get("senha","")
    erros=[]
    if not 2<=len(nome)<=120:
        erros.append("Nome deve ter de 2 a 120 caracteres.")
    if len(email)>254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",email):
        erros.append("Informe um e-mail válido.")
    if perfil not in PERFIS or ativo not in {"sim","nao"}:
        erros.append("Perfil ou situação inválidos.")
    if not registro or senha:
        if not 12<=len(senha)<=128:
            erros.append("A senha deve ter de 12 a 128 caracteres.")
        if senha!=valores.get("confirmacao",""):
            erros.append("As senhas não conferem.")
    elif valores.get("confirmacao"):
        erros.append("Preencha a nova senha para confirmá-la.")
    if registro and registro.id==g.usuario.id and (perfil!="Administrador" or ativo!="sim"):
        erros.append("Você não pode desativar ou reduzir o perfil da sua própria conta.")
    dados=dict(nome=nome,email=email,perfil=perfil,ativo=ativo=="sim")
    if senha and not erros:
        dados["senha_hash"]=generate_password_hash(senha)
    return dados,erros


def ler_convenios_gestor(form, perfil, erros):
    ids = sorted({inteiro(x) for x in form.getlist("convenio_ids") if inteiro(x)})
    validos = set(db.session.scalars(select(Convenio.id).where(Convenio.id.in_(ids or [-1]))))
    if perfil == "Gestor de convênio" and not validos:
        erros.append("Marque pelo menos um convênio para o Gestor de convênio.")
    return sorted(validos) if perfil == "Gestor de convênio" else []


def salvar_convenios_gestor(usuario, ids):
    db.session.execute(delete(GestorConvenio).where(GestorConvenio.usuario_id == usuario.id))
    for cid in ids:
        db.session.add(GestorConvenio(usuario_id=usuario.id, convenio_id=cid))


def auditar_usuario(usuario,acao):
    db.session.add(AuditoriaUsuario(autor_id=g.usuario.id,usuario_id=usuario.id,acao=acao))


@app.route("/cadastros/usuarios",methods=["GET","POST"])
@login_obrigatorio
def usuarios_cadastro():
    if request.method=="GET":
        return tela_registro("usuarios")
    dados,erros=validar_usuario(request.form)
    convenios_ids=ler_convenios_gestor(request.form,dados["perfil"],erros)
    if erros:
        return tela_registro("usuarios",request.form,erros,status=422)
    try:
        usuario=Usuario(**dados)
        db.session.add(usuario)
        db.session.flush()
        salvar_convenios_gestor(usuario,convenios_ids)
        auditar_usuario(usuario,"Criação da conta")
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return tela_registro("usuarios",request.form,["Já existe um usuário com esse e-mail."],status=409)
    flash("Usuário cadastrado. O acesso já está disponível, se a conta estiver ativa.")
    return redirect(url_for("usuarios_cadastro"))


@app.route("/cadastros/usuarios/<int:usuario_id>/editar",methods=["GET","POST"])
@login_obrigatorio
def editar_usuario(usuario_id):
    # Serializes admin changes before verifying the last active administrator.
    if request.method=="POST" and db.engine.dialect.name=="postgresql":
        db.session.execute(text("SELECT pg_advisory_xact_lock(739105633)"))
    consulta=select(Usuario).where(Usuario.id==usuario_id)
    if request.method=="POST":
        consulta=consulta.with_for_update().execution_options(populate_existing=True)
    usuario=db.session.scalar(consulta)
    if usuario is None:
        abort(404)
    if request.method=="GET":
        return tela_registro("usuarios",dict(nome=usuario.nome,email=usuario.email,perfil=usuario.perfil,
            ativo="sim" if usuario.ativo else "nao",revisao=usuario.versao_sessao),registro=usuario)
    dados,erros=validar_usuario(request.form,usuario)
    convenios_ids=ler_convenios_gestor(request.form,dados["perfil"],erros)
    if request.form.get("revisao")!=str(usuario.versao_sessao):
        erros.append("Essa conta foi alterada em outra tela. Reabra a edição.")
    if usuario.ativo and usuario.perfil=="Administrador" and (not dados["ativo"] or dados["perfil"]!="Administrador"):
        outros=db.session.scalar(select(func.count(Usuario.id)).where(Usuario.id!=usuario_id,Usuario.ativo.is_(True),Usuario.perfil=="Administrador"))
        if not outros:
            erros.append("Mantenha pelo menos um administrador ativo.")
    if erros:
        db.session.rollback()
        return tela_registro("usuarios",request.form,erros,registro=usuario,status=422)
    redefiniu="senha_hash" in dados
    for campo,valor in dados.items():
        setattr(usuario,campo,valor)
    salvar_convenios_gestor(usuario,convenios_ids)
    usuario.versao_sessao+=1
    auditar_usuario(usuario,"Alteração da conta e redefinição de senha" if redefiniu else "Alteração da conta")
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return tela_registro("usuarios",request.form,["E-mail já usado em outra conta."],registro=usuario,status=409)
    if usuario.id==g.usuario.id:
        session.clear()
        flash("Sua conta foi atualizada. Entre novamente.")
        return redirect(url_for("login"))
    flash("Usuário atualizado. As sessões anteriores foram encerradas.")
    return redirect(url_for("usuarios_cadastro"))


GUIA_TOPICOS = [
    dict(titulo='Cadastro e plaqueta', resumo='Identificar o bem', texto='Cada bem do projeto ganha um número próprio, que fica preso nele por plaqueta ou etiqueta. Esse número liga o bem que está na base ao cadastro do sistema. A IN 205 orienta numerar os bens em sequência e marcar o número no próprio bem (itens 7.13 e 7.13.1).', pratica='Cadastre o bem em Bens patrimoniais. Se ele já veio com plaqueta, informe a plaqueta original; se não veio, gere o número de patrimônio e imprima a etiqueta em Plaquetas.', exemplo='Um notebook comprado pelo projeto chega à base: é cadastrado com marca, modelo, série e nota fiscal (quando houver) e recebe a plaqueta antes de ser entregue a quem vai usá-lo.', alerta='', fontes=[('IN SEDAP nº 205/1988, itens 7.13 e 7.13.1', 'https://www.gov.br/compras/pt-br/acesso-a-informacao/legislacao/instrucoes-normativas/instrucao-normativa-no-205-de-08-de-abril-de-1988')]),
    dict(titulo='Termo de responsabilidade', resumo='Quem responde pelo bem', texto='Todo bem entregue para uso precisa de um responsável, e isso se formaliza com o termo de responsabilidade assinado por quem recebe (itens 7.11 e 7.12). Quando o bem muda de local ou de responsável, faz-se um novo termo (item 7.13.3).', pratica='Em Termos e documentos, emita o termo e use Enviar para aceite: a pessoa recebe o link no e-mail e aceita, sem precisar de login.', exemplo='Ao entregar um GPS ao analista de campo, emita o termo e envie o link para o e-mail dele. O aceite fica registrado no termo com data, hora e comprovante.', alerta='', fontes=[('IN SEDAP nº 205/1988, itens 7.11, 7.12 e 7.13.3', 'https://www.gov.br/compras/pt-br/acesso-a-informacao/legislacao/instrucoes-normativas/instrucao-normativa-no-205-de-08-de-abril-de-1988')]),
    dict(titulo='Uso e cuidado', resumo='Conservar e avisar', texto='Quem recebeu o bem cuida dele e avisa o patrimônio na hora se algo acontecer: dano, defeito, sumiço (itens 7.13.7 e 10.1). Também não deve levar o bem para outro lugar sem o patrimônio saber (item 7.13.4).', pratica='Registre o fato em Termos e documentos → Relatório de ocorrência e atualize a situação e a conservação na ficha do bem.', exemplo='A câmera trap caiu e a lente trincou: o responsável avisa, o patrimônio emite o relatório de ocorrência e muda a situação do bem para Manutenção.', alerta='', fontes=[('IN SEDAP nº 205/1988, itens 7.13.4, 7.13.7 e 10.1', 'https://www.gov.br/compras/pt-br/acesso-a-informacao/legislacao/instrucoes-normativas/instrucao-normativa-no-205-de-08-de-abril-de-1988')]),
    dict(titulo='Movimentação', resumo='Registrar a mudança', texto='Toda vez que um bem muda de base, de sala ou de responsável, a mudança é registrada e o termo é refeito (item 7.13.3). Assim dá para saber, a qualquer momento, onde cada bem está e com quem.', pratica='Use Movimentações: escolha o bem, o destino e o novo responsável. Ao confirmar a entrega, o sistema atualiza o cadastro e emite o termo de movimentação.', exemplo='Uma impressora vai do escritório de Parauapebas para a Base Gavião Real: registre o remanejamento, confirme a chegada e envie o termo para o aceite de quem a recebeu.', alerta='', fontes=[('IN SEDAP nº 205/1988, itens 7.13.3 e 7.13.4', 'https://www.gov.br/compras/pt-br/acesso-a-informacao/legislacao/instrucoes-normativas/instrucao-normativa-no-205-de-08-de-abril-de-1988')]),
    dict(titulo='Inventário', resumo='Conferir fisicamente', texto='Inventário é ir até os bens e conferir se estão onde o sistema diz, com quem e em que estado (item 8). A IN 205 prevê o inventário anual e também inventários em momentos de mudança, como troca de responsável pela unidade (item 8.1). Quem confere é uma comissão designada (item 8.4).', pratica='Em Inventário, abra a campanha, leia o QR Code das plaquetas e marque cada bem como Conferido, Divergência ou Não localizado. O resultado aparece em Relatórios → Indicadores de gestão.', exemplo='Inventário anual na Base Gavião Real: 120 bens previstos, 114 conferidos, 4 com divergência e 2 não localizados. Acurácia de 95%. Os 2 não localizados vão para apuração.', alerta='Bem não localizado é para apurar, não para dar baixa direto.', fontes=[('IN SEDAP nº 205/1988, itens 8, 8.1 e 8.4', 'https://www.gov.br/compras/pt-br/acesso-a-informacao/legislacao/instrucoes-normativas/instrucao-normativa-no-205-de-08-de-abril-de-1988')]),
    dict(titulo='Bens sem uso', resumo='Avaliar a utilidade', texto='Bem parado não é bem perdido. O Decreto nº 12.785/2025 separa o bem em uso; o ocioso (funciona, mas ninguém usa); o recuperável (o conserto custa até metade do valor de mercado); o antieconômico (manter custa mais do que vale); e o irrecuperável (não serve mais). A IN 205 orienta oferecer os ociosos para quem precise (item 11.2.1).', pratica='O indicador Bens parados mostra os bens Disponíveis ou em Manutenção há muito tempo, para a equipe decidir se redistribui, conserta ou encaminha para baixa.', exemplo='Conserto de R$ 800 num notebook que vale R$ 3.000 (27%): vale consertar. Conserto de R$ 2.000 no mesmo notebook (67%): passa da metade e o conserto deixa de compensar.', alerta='', fontes=[('Decreto nº 12.785/2025, art. 3º', 'https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2025/decreto/d12785.htm'), ('IN SEDAP nº 205/1988, item 11.2.1', 'https://www.gov.br/compras/pt-br/acesso-a-informacao/legislacao/instrucoes-normativas/instrucao-normativa-no-205-de-08-de-abril-de-1988')]),
    dict(titulo='Saída do bem', resumo='Definir o destino', texto='Quando o bem não serve mais ao projeto, ele pode ser emprestado (cessão), repassado (transferência), doado, leiloado ou, se não tiver mais uso, descartado de forma ambientalmente correta (Decreto nº 12.785/2025, arts. 4º a 18). Ao fim do projeto, o destino dos bens segue o que o acordo de cooperação prevê.', pratica='Em Encerramento e baixa, registre o motivo, a decisão e o destino, e anexe os comprovantes.', exemplo='Monitores sem conserto: a equipe avalia, oferece primeiro ao Programa Computadores para Inclusão (30 dias, art. 12) e só depois decide entre doação e descarte adequado.', alerta='', fontes=[('Decreto nº 12.785/2025, arts. 4º a 18', 'https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2025/decreto/d12785.htm')]),
    dict(titulo='Venda ou doação', resumo='Passar o bem adiante', texto='Vender ou doar um bem público (alienação) exige justificar o interesse público e avaliar o bem antes (Lei nº 14.133/2021, art. 76).', pratica='Registre a decisão, a avaliação e o termo de doação no processo de baixa antes de entregar o bem.', exemplo='Uma doação autorizada não é só entregar o bem: o processo guarda a avaliação, a autorização e o termo assinado.', alerta='', fontes=[('Lei nº 14.133/2021, art. 76', 'https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2021/lei/l14133.htm')]),
    dict(titulo='Baixa', resumo='Fechar o registro', texto='Baixa é tirar o bem do acervo ativo depois que a saída foi decidida e documentada. O cadastro não é apagado: o histórico fica guardado para consulta e prestação de contas do projeto.', pratica='No sistema, a baixa tira o bem da lista de ativos, mas mantém a ficha, o histórico, os termos e os anexos.', exemplo='Depois da doação dos monitores, registre a baixa com o número do processo, o motivo e os comprovantes.', alerta='', fontes=[('MCASP, 11ª edição, Parte II, item 11.8 — Tesouro Nacional', 'https://cdn.tesouro.gov.br/sistemas-internos/apex/producao/sistemas/thot/arquivos/publicacoes/51045_2434252/MCASP%20-%2011%C2%AA%20Edi%C3%A7%C3%A3o.pdf#page=235')]),
    dict(titulo='Indicadores', resumo='Medir o controle', texto='Os relatórios de inventário da Administração Pública Federal acompanham, por exemplo, o percentual de bens não localizados: não localizados ÷ total de bens × 100. O relatório de 2025 da AGU registra 150 não localizados em 2.739 bens de uma unidade (5,48%).', pratica='Em Relatórios → Indicadores de gestão, o sistema calcula acurácia, não localizados, divergências, bens parados e cobertura de termos, cada um com fórmula e exemplo.', exemplo='Se o percentual de não localizados cai de 8% para 3% entre dois inventários, o controle melhorou.', alerta='', fontes=[('AGU — Relatório de inventário de bens móveis e imóveis 2025', 'https://www.gov.br/agu/pt-br/acesso-a-informacao/patrimonio/resultados/RelatrioInventrioBensMveiseImveis2025.pdf'), ('IN SEDAP nº 205/1988, item 8', 'https://www.gov.br/compras/pt-br/acesso-a-informacao/legislacao/instrucoes-normativas/instrucao-normativa-no-205-de-08-de-abril-de-1988')]),
]


@app.get("/guia-patrimonial")
@login_obrigatorio
def guia_patrimonial():
    return render_template_string(TEMPLATE,bem=None,formulario=False,guia_page=True,
                                  topicos_guia=GUIA_TOPICOS,**contexto_painel())


# ============================================================
# ADMINISTRADOR CONFIGURADO PELO ENVIRONMENT DO RENDER
# Nenhuma senha padrão é incluída no código ou enviada ao navegador.
# ============================================================
OP_TEMPLATES = {
'op_tabs': r'''<nav class="registry-navigation" aria-label="Navegação do módulo"><a href="{{ url_for(op_endpoint) }}" class="{{ 'current' if not op_form }}" {% if not op_form %}aria-current="page"{% endif %}>{{ op_lista }}</a>{% if not usuario.leitura %}<a href="{{ url_for(op_endpoint,aba='cadastro') }}" class="{{ 'current' if op_form }}" {% if op_form %}aria-current="page"{% endif %}>{{ op_novo }}</a>{% endif %}</nav>''',
'op_erros': r'''{% if erros %}<div class="erros" role="alert"><strong>Confira as informações:</strong><ul>{% for erro in erros %}<li>{{ erro }}</li>{% endfor %}</ul></div>{% endif %}''',
'op_token': r'''<input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><input type="hidden" name="operacao_token" value="{{ operacao_token }}">''',
'op_paginacao': r'''<div class="pagination-bar"><span>{{ primeiro_operacao }}–{{ ultimo_operacao }} de {{ quantidade_operacao }} registros</span><nav class="pagination" aria-label="Páginas">{% if pagina_operacao>1 %}<a href="{{ url_operacao_pagina(pagina_operacao-1) }}">Anterior</a>{% endif %}{% for n in numeros_operacao %}{% if not loop.first and n>numeros_operacao[loop.index0-1]+1 %}<span>…</span>{% endif %}{% if n==pagina_operacao %}<span class="current-page" aria-current="page">{{ n }}</span>{% else %}<a href="{{ url_operacao_pagina(n) }}">{{ n }}</a>{% endif %}{% endfor %}{% if pagina_operacao<paginas_operacao %}<a href="{{ url_operacao_pagina(pagina_operacao+1) }}">Próxima</a>{% endif %}</nav></div>''',
'op_busca_bem': r'''<section class="panel op-picker op-picker-v2" aria-labelledby="bem-picker-titulo">
<div class="picker-heading"><div><h2 id="bem-picker-titulo">{{ 'Bem a movimentar' if op_endpoint=='movimentacoes' else 'Bem vinculado ao documento' if op_endpoint=='documentos' else 'Bem a analisar' }}</h2><p>{{ 'Selecione primeiro o local de origem e depois o bem que deseja movimentar.' if op_endpoint=='movimentacoes' else 'Busque e selecione um bem cadastrado. Os dados atuais aparecerão abaixo.' }}</p></div><span class="picker-state" id="picker-state">{{ 'Bem selecionado' if bem_escolhido else 'Seleção pendente' }}</span></div>
{% if op_endpoint=='movimentacoes' %}<div class="field" style="margin-bottom:20px"><label for="picker-origin-base">1. Local de origem do bem *</label><select id="picker-origin-base" style="width:100%;min-height:46px" {% if retorno %}disabled{% endif %}><option value="">Selecione um local cadastrado</option>{% for b in bases_origem %}<option value="{{ b.id }}" {{ 'selected' if origem_selecionada==b.id|string }}>{{ b.nome }}{{ ' (inativo)' if not b.ativo }}</option>{% endfor %}{% if tem_bens_sem_base or origem_selecionada=='sem_base' %}<option value="sem_base" {{ 'selected' if origem_selecionada=='sem_base' }}>Bens sem vínculo com local cadastrado</option>{% endif %}</select><small>A busca considera o vínculo atual do bem com o local cadastrado. O destino será informado separadamente abaixo.</small></div>{% endif %}<div class="picker-search" {% if retorno %}hidden{% endif %}><div class="field"><label for="buscar-bem">{{ '2. Buscar bem neste local *' if op_endpoint=='movimentacoes' else 'Buscar bem cadastrado *' }}</label><div class="picker-input-row"><input id="buscar-bem" type="search" maxlength="120" autocomplete="off" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="picker-results" placeholder="Nome do bem, número de série ou plaqueta" value="{{ buscar_bem }}"><button class="btn" type="button" id="picker-search-button">Buscar bem</button></div><small>{{ 'Escolha um local para liberar a busca. São exibidos até 15 bens por consulta; digite para refinar.' if op_endpoint=='movimentacoes' else 'Clique no campo para consultar os bens recentes ou digite uma identificação.' }}</small></div>
<div class="picker-results" id="picker-results" role="listbox" aria-label="Bens encontrados" hidden></div><p id="picker-feedback" role="status" aria-live="polite"></p></div>
<div class="picker-selected-header"><div><span class="picker-eyebrow">BEM SELECIONADO</span><h3 id="picker-name">{{ bem_escolhido.nome if bem_escolhido else 'Selecione um bem na busca acima' }}</h3><p id="picker-identification">{{ (bem_escolhido.patrimonio ~ ' · Série: ' ~ (bem_escolhido.serie or bem_escolhido.serie_excecao)) if bem_escolhido else 'A identificação será preenchida automaticamente.' }}</p></div><a class="text-action" id="picker-open" href="{{ url_for('ficha',bem_id=bem_escolhido.id) if bem_escolhido else '#' }}" target="_blank" rel="noopener" {% if not bem_escolhido %}hidden{% endif %}>Abrir ficha ↗</a></div>
<div class="picker-origin"><div><span>Local atual · origem</span><strong id="picker-origin-place">{{ bem_escolhido.local if bem_escolhido else 'Aguardando seleção do bem' }}</strong><small id="picker-origin-address">{{ bem_escolhido.endereco if bem_escolhido else 'Endereço cadastrado do local de origem' }}</small></div><div><span>Responsável atual</span><strong id="picker-origin-person">{{ bem_escolhido.responsavel if bem_escolhido else 'Aguardando seleção do bem' }}</strong><small id="picker-origin-agreement">{{ bem_escolhido.convenio if bem_escolhido else 'Convênio / projeto vinculado ao bem' }}</small></div></div>
</section>
<script>
document.addEventListener('DOMContentLoaded',()=>{
const input=document.querySelector('#buscar-bem'),list=document.querySelector('#picker-results'),feedback=document.querySelector('#picker-feedback');
const fields=document.querySelector('.op-data-fields'),hint=document.querySelector('#op-selection-hint');
const origin=document.querySelector('#picker-origin-base'),searchButton=document.querySelector('#picker-search-button');
let lastOrigin=origin?.value||'';
let sequence=0,controller,timer,selected={{ bem_escolhido.id|tojson if bem_escolhido else 'null' }};
function close(){list.hidden=true;input.setAttribute('aria-expanded','false');}
function choose(b){
 if(selected&&selected!==b.id&&document.querySelector('.op-entry-form form')?.dataset.dirty==='true'&&!window.confirm('Trocar o bem e manter os dados de destino já preenchidos? Confira se eles se aplicam ao novo bem.'))return;
 selected=b.id;document.querySelectorAll('input[name="bem_id"]').forEach(x=>x.value=String(b.id));document.querySelectorAll('input[name="revisao_bem"]').forEach(x=>x.value=String(b.revisao));
 document.querySelector('#picker-name').textContent=b.nome;document.querySelector('#picker-identification').textContent=b.patrimonio+' · Série: '+b.serie;
 document.querySelector('#picker-origin-place').textContent=b.local;document.querySelector('#picker-origin-address').textContent=b.endereco;
 document.querySelector('#picker-origin-person').textContent=b.responsavel;document.querySelector('#picker-origin-agreement').textContent=b.convenio;
 document.querySelector('#picker-state').textContent='Bem selecionado';const link=document.querySelector('#picker-open');link.href=b.url;link.hidden=false;
 if(fields)fields.disabled=false;if(hint)hint.hidden=true;input.value=b.nome;feedback.textContent='Bem selecionado. Preencha os dados abaixo.';close();
}
async function search(){
 if(origin&&!origin.value){feedback.textContent='Selecione primeiro o local de origem.';close();return;}
 const turn=++sequence;if(controller)controller.abort();controller=new AbortController();list.replaceChildren();list.hidden=false;input.setAttribute('aria-expanded','true');feedback.textContent='Buscando bens…';
 try{const url=new URL({{ url_for('pesquisar_bens_operacao')|tojson }},location.origin);url.searchParams.set('q',input.value.trim());if(origin){url.searchParams.set('origem',origin.value);url.searchParams.set('exigir_local','sim');}const response=await fetch(url,{headers:{Accept:'application/json'},signal:controller.signal});
 if(response.redirected)throw new Error('Sua sessão expirou. Preserve o preenchimento antes de entrar novamente.');if(!response.ok)throw new Error('Não foi possível buscar os bens. Tente novamente.');const data=await response.json();if(turn!==sequence)return;
 data.bens.forEach(b=>{const button=document.createElement('button');button.type='button';button.className='picker-result';button.setAttribute('role','option');button.setAttribute('aria-selected',String(b.id===selected));
 const title=document.createElement('strong'),detail=document.createElement('span'),place=document.createElement('small');title.textContent=b.nome;detail.textContent=b.patrimonio+' · Série: '+b.serie;place.textContent=b.local+' · '+b.responsavel;
 button.append(title,detail,place);button.addEventListener('click',()=>choose(b));button.addEventListener('keydown',e=>{if(e.key==='ArrowDown'){e.preventDefault();button.nextElementSibling?.focus();}if(e.key==='ArrowUp'){e.preventDefault();(button.previousElementSibling||input).focus();}if(e.key==='Escape'){close();input.focus();}});list.append(button);});
 feedback.textContent=data.bens.length?(data.tem_mais?'Mostrando 15 bens. Refine a busca para localizar outros.':'Clique no bem desejado para selecionar.'):'Nenhum bem ativo encontrado. Busque pelo número de série ou pela plaqueta.';
 if(!data.bens.length){const empty=document.createElement('p');empty.className='picker-no-results';empty.textContent='Nenhum bem encontrado.';list.append(empty);}
 }catch(e){if(e.name==='AbortError'||turn!==sequence)return;close();feedback.textContent=e.message||'Falha de conexão. Tente novamente.';}
}
function syncOrigin(){
 document.querySelectorAll('input[name="base_origem"]').forEach(x=>x.value=origin?.value||'');
 input.disabled=!!origin&&!origin.value;searchButton.disabled=input.disabled;
 if(input.disabled)feedback.textContent='Selecione primeiro o local de origem.';
}
if(origin){syncOrigin();origin.addEventListener('change',()=>{
 const form=document.querySelector('.op-entry-form form');
 if(selected&&form?.dataset.dirty==='true'&&!window.confirm('Trocar o local e limpar o bem selecionado? Os dados de destino serão mantidos para sua revisão.')){origin.value=lastOrigin;return;}
 lastOrigin=origin.value;clearTimeout(timer);sequence++;if(controller)controller.abort();selected=null;input.value='';close();
 document.querySelectorAll('input[name="bem_id"],input[name="revisao_bem"]').forEach(x=>x.value='');
 document.querySelector('#picker-name').textContent='Selecione um bem deste local';document.querySelector('#picker-identification').textContent='A identificação será preenchida automaticamente.';
 for(const id of ['picker-origin-place','picker-origin-address','picker-origin-person','picker-origin-agreement'])document.getElementById(id).textContent='Aguardando seleção do bem';
 document.querySelector('#picker-state').textContent='Seleção pendente';document.querySelector('#picker-open').hidden=true;if(fields)fields.disabled=true;if(hint)hint.hidden=false;
 syncOrigin();if(origin.value){feedback.textContent='Selecione um bem deste local.';search();}
 });}
input.addEventListener('focus',()=>{if(list.hidden)search();});input.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(search,250);});
input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();clearTimeout(timer);search();}if(e.key==='ArrowDown'){e.preventDefault();if(list.hidden)search();else list.querySelector('button')?.focus();}if(e.key==='Escape')close();});
document.querySelector('#picker-search-button').addEventListener('click',()=>{clearTimeout(timer);search();});document.addEventListener('click',e=>{if(!e.target.closest('.picker-search'))close();});
const form=document.querySelector('.op-entry-form form');if(form)form.addEventListener('input',()=>form.dataset.dirty='true');
const tipo=document.querySelector('#mov-tipo'),previsao=document.querySelector('#mov-previsao');function updateType(){if(!tipo||!previsao)return;const temporary=['Entrega temporária','Manutenção'].includes(tipo.value);previsao.required=temporary;previsao.closest('.field').hidden=!temporary;const text=document.querySelector('#mov-type-help');if(text)text.textContent=tipo.value==='Remanejamento interno'?'Altera o local ou o responsável do bem dentro do controle do NGI.':tipo.value==='Entrega temporária'?'Registra uma entrega com retorno previsto. A devolução ficará vinculada a esta movimentação.':'Registra o envio para manutenção, com previsão de retorno e devolução vinculada.';}
if(tipo)tipo.addEventListener('change',updateType);updateType();
});
</script>
''',
'mov_lista': r'''
<div class="list-heading"><div><h1>Movimentações</h1><p>Acompanhe mudanças de local, responsabilidade e entregas temporárias.</p></div></div>{% include 'op_tabs' %}
<section class="panel"><form method="get" class="registry-toolbar"><div class="field"><label for="mov-q">Pesquisar bem</label><input id="mov-q" name="q" value="{{ q }}" placeholder="Nome, série ou nº de patrimônio" maxlength="120"></div><div class="field"><label for="mov-status">Situação</label><select name="status" id="mov-status"><option value="">Todas</option>{% for st in ['Pendente','Concluída','Cancelada'] %}<option {{ 'selected' if filtro==st }}>{{ st }}</option>{% endfor %}<option value="atrasados" {{ 'selected' if filtro=='atrasados' }}>Devoluções atrasadas</option></select></div><button class="btn primary">Pesquisar</button></form>
<div class="tablewrap"><table><thead><tr><th>Registro / bem</th><th>Tipo</th><th>Origem → destino</th><th>Responsável no destino</th><th>Situação</th><th></th></tr></thead><tbody>{% for m in rows %}<tr><td><strong>MOV-{{ '%06d'|format(m.id) }}</strong><small class="table-sub">{{ m.origem.nome }}</small></td><td>{{ m.tipo }}{% if m.previsao_retorno and not m.devolvido_em and m.status=='Concluída' %}<small class="table-sub">Retorno: {{ m.previsao_retorno|datahora }}</small>{% endif %}</td><td>{{ m.origem.local }} → {{ m.destino.local }}</td><td>{{ m.destino.responsavel }}</td><td><span class="badge {{ 'warn' if m.status=='Pendente' }}">{{ m.status }}</span></td><td><a class="text-action" href="{{ url_for('movimento_detalhe',movimento_id=m.id) }}">Abrir</a></td></tr>{% else %}<tr><td colspan="6" class="list-empty">Nenhuma movimentação encontrada.</td></tr>{% endfor %}</tbody></table></div>{% include 'op_paginacao' %}</section>''',
'mov_form': r'''
<div class="list-heading"><div><h1>{{ 'Registrar devolução' if retorno else 'Nova movimentação' }}</h1><p>Selecione o bem e informe o destino. A atualização ocorre após confirmar a entrega.</p></div></div>{% include 'op_tabs' %}{% include 'op_erros' %}{% include 'op_busca_bem' %}
<section class="form-section registry-form op-entry-form"><h2>Destino e responsabilidade</h2><form method="post" action="{{ url_for('movimentacoes') }}">{% include 'op_token' %}<input type="hidden" name="base_origem" value="{{ origem_selecionada }}"><input type="hidden" name="bem_id" value="{{ bem_escolhido.id }}"><input type="hidden" name="revisao_bem" value="{{ bem_escolhido.revisao }}">{% if retorno %}<input type="hidden" name="retorno_de" value="{{ retorno.id }}"><p class="hint">Devolução de MOV-{{ '%06d'|format(retorno.id) }}. Confira o local e a pessoa que receberá o bem.</p>{% endif %}
<p class="op-selection-hint" id="op-selection-hint" {% if bem_escolhido %}hidden{% endif %}>Selecione o bem acima para preencher o destino e registrar a solicitação.</p><fieldset class="op-data-fields" {% if not bem_escolhido %}disabled{% endif %}><div class="fields">{% if not retorno %}<div class="field"><label for="mov-tipo">Tipo *</label><select name="tipo" id="mov-tipo" required>{% for t in tipos_movimento %}<option {{ 'selected' if valores.get('tipo')==t }}>{{ t }}</option>{% endfor %}</select><small id="mov-type-help">Altera o local ou o responsável do bem dentro do controle do NGI.</small></div>{% endif %}
<div class="field"><label for="mov-base">Base / local de destino *</label><select id="mov-base" name="base_id" required><option value="">Selecione</option>{% for b in bases_destino %}<option value="{{ b.id }}" {{ 'selected' if valores.get('base_id',retorno.origem.base_id if retorno else '')|string == b.id|string }}>{{ b.nome }}</option>{% endfor %}</select></div>
<div class="field"><label for="mov-responsavel">Responsável no destino *</label><input id="mov-responsavel" name="responsavel" required maxlength="160" value="{{ valores.get('responsavel',retorno.origem.responsavel if retorno else '') }}"></div><div class="field"><label for="mov-contato">Contato do responsável</label><input id="mov-contato" name="contato" maxlength="160" value="{{ valores.get('contato','') }}"></div>
<div class="field"><label for="mov-sala">Sala / complemento no destino</label><input id="mov-sala" name="complemento" maxlength="200" value="{{ valores.get('complemento','') }}"></div><div class="field"><label for="mov-previsao">Previsão de retorno</label><input id="mov-previsao" type="date" name="previsao_retorno" value="{{ valores.get('previsao_retorno','') }}"><small>Obrigatória para entrega temporária e manutenção.</small></div>
<div class="field wide"><label for="mov-referencia">Processo / autorização / referência</label><input id="mov-referencia" name="referencia" maxlength="200" value="{{ valores.get('referencia','') }}"></div><div class="field wide"><label for="mov-motivo">Justificativa *</label><textarea id="mov-motivo" name="motivo" required minlength="10" maxlength="3000">{{ valores.get('motivo','') }}</textarea></div></div>
<div class="dialog-actions"><a class="btn" href="{{ url_for('movimentacoes') }}">Cancelar</a><button class="btn primary">Registrar solicitação</button></div></fieldset></form></section>''',
'mov_detalhe': r'''
<a class="back" href="{{ url_for('movimentacoes') }}">← Movimentações</a><div class="list-heading"><div><h1>MOV-{{ '%06d'|format(mov.id) }}</h1><p>{{ ativo.nome }} · {{ mov.tipo }}</p></div><span class="badge">{{ mov.status }}</span></div>
<div class="op-detail-grid"><section class="panel"><h2>Origem</h2><dl class="compact-facts"><div><dt>Local</dt><dd>{{ mov.origem.local }}</dd></div><div><dt>Responsável</dt><dd>{{ mov.origem.responsavel }}</dd></div></dl></section><section class="panel"><h2>Destino solicitado</h2><dl class="compact-facts"><div><dt>Local</dt><dd>{{ mov.destino.local }}</dd></div><div><dt>Responsável</dt><dd>{{ mov.destino.responsavel }}</dd></div><div><dt>Sala / complemento</dt><dd>{{ mov.destino.complemento or '—' }}</dd></div></dl></section></div>
<section class="panel op-section"><h2>Registro da movimentação</h2><p class="detail-description">{{ mov.motivo }}</p><dl class="compact-facts"><div><dt>Processo / referência</dt><dd>{{ mov.referencia or '—' }}</dd></div><div><dt>Registrado por</dt><dd>{{ mov.criado_nome }} · {{ mov.criado_em|datahora }}</dd></div><div><dt>Previsão de retorno</dt><dd>{{ mov.previsao_retorno|datahora }}</dd></div>{% if mov.devolvido_em %}<div><dt>Devolução confirmada</dt><dd>{{ mov.devolvido_em|datahora }}</dd></div>{% endif %}{% if mov.motivo_cancelamento %}<div><dt>Motivo do cancelamento</dt><dd>{{ mov.motivo_cancelamento }}</dd></div>{% endif %}</dl>
<div class="op-actions"><a class="btn" href="{{ url_for('ficha',bem_id=ativo.id,consulta=1) }}">Consultar bem</a>{% if documento %}<a class="btn primary" href="{{ url_for('documento_detalhe',documento_id=documento.id) }}">Abrir termo</a>{% endif %}{% if mov.tipo in ['Entrega temporária','Manutenção'] and mov.status=='Concluída' and not mov.devolvido_em and not usuario.leitura %}<a class="btn primary" href="{{ url_for('movimentacoes',aba='cadastro',bem_id=ativo.id,retorno_de=mov.id) }}">Registrar devolução</a>{% endif %}</div></section>
{% if mov.status=='Pendente' and not usuario.leitura %}<section class="form-section registry-form"><h2>Confirmar entrega</h2><p>Confirme somente após a entrega física. Local e responsável serão atualizados e o termo será emitido.</p><form method="post" action="{{ url_for('confirmar_movimento',movimento_id=mov.id) }}"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><label class="op-check"><input type="checkbox" name="confirmar" value="sim" required> Confirmo a entrega do bem ao destino e ao responsável informados.</label><div class="dialog-actions"><button class="btn primary">Confirmar movimentação</button></div></form></section>
<details class="panel op-section"><summary>Cancelar solicitação</summary><form method="post" action="{{ url_for('cancelar_movimento',movimento_id=mov.id) }}"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><div class="field"><label for="cancelar-mov">Motivo *</label><textarea id="cancelar-mov" name="motivo" minlength="10" maxlength="2000" required></textarea></div><div class="dialog-actions"><button class="btn">Cancelar movimentação</button></div></form></details>{% endif %}''',
'doc_lista': r'''
<div class="list-heading"><div><h1>Termos e documentos</h1><p>Consulte termos emitidos, registros de ocorrência e seus comprovantes.</p></div></div>{% include 'op_tabs' %}<section class="panel"><form method="get" class="registry-toolbar"><div class="field"><label for="doc-q">Pesquisar documentos</label><input id="doc-q" name="q" maxlength="120" value="{{ q }}" placeholder="Tipo do documento ou nome do bem"></div><button class="btn primary">Pesquisar</button></form><div class="tablewrap"><table><thead><tr><th>Número</th><th>Documento / bem</th><th>Emitido por</th><th>Emissão</th><th></th></tr></thead><tbody>{% for d in rows %}<tr><td>DOC-{{ '%06d'|format(d.id) }}</td><td><strong>{{ d.tipo }}</strong><small class="table-sub">{{ d.resumo }}</small>{% set sa = situacao_aceite.get(d.id) %}{% if sa %}<span class="badge {{ 'warn' if sa != 'Aceito' }}" style="margin-top:6px">Aceite: {{ sa|lower }}</span>{% endif %}</td><td>{{ d.autor_nome }}</td><td>{{ d.criado_em|datahora }}</td><td><a class="text-action" href="{{ url_for('documento_detalhe',documento_id=d.id) }}">Abrir</a></td></tr>{% else %}<tr><td colspan="5" class="list-empty">Nenhum documento emitido.</td></tr>{% endfor %}</tbody></table></div>{% include 'op_paginacao' %}</section>''',
'doc_form': r'''
<div class="list-heading"><div><h1>Emitir documento</h1><p>Movimentações e baixas geram documentos próprios. Aqui, emita responsabilidade ou ocorrência.</p></div></div>{% include 'op_tabs' %}{% include 'op_erros' %}<div class="kit-atalho"><div><strong>A pessoa está com vários bens?</strong><span>Emita um termo só, com notebook, monitor e teclado juntos, e um aceite só.</span></div><a class="btn" href="{{ url_for('termo_kit') }}">Termo com vários bens</a></div>{% include 'op_busca_bem' %}
<section class="form-section registry-form op-entry-form"><h2>Informações do documento</h2><form method="post">{% include 'op_token' %}<input type="hidden" name="bem_id" value="{{ bem_escolhido.id }}"><p class="op-selection-hint" id="op-selection-hint" {% if bem_escolhido %}hidden{% endif %}>Selecione o bem acima para preencher e salvar este registro.</p><fieldset class="op-data-fields" {% if not bem_escolhido %}disabled{% endif %}><div class="fields"><div class="field"><label for="doc-tipo">Tipo *</label><select id="doc-tipo" name="tipo">{% for t in ['Termo de responsabilidade','Relatório de ocorrência'] %}<option {{ 'selected' if valores.get('tipo')==t }}>{{ t }}</option>{% endfor %}</select></div><div class="field"><label for="doc-ref">Processo / referência</label><input id="doc-ref" name="referencia" maxlength="200" value="{{ valores.get('referencia','') }}"></div><div class="field wide"><label for="doc-texto">Descrição / finalidade *</label><textarea id="doc-texto" name="justificativa" minlength="10" maxlength="5000" required>{{ valores.get('justificativa','') }}</textarea></div></div><p class="hint">O documento guarda os dados atuais do bem. Após emitir, imprima para colher as assinaturas e anexe o comprovante assinado.</p><div class="dialog-actions"><a class="btn" href="{{ url_for('documentos') }}">Cancelar</a><button class="btn primary">Emitir documento</button></div></fieldset></form></section>''',
'doc_kit_form': r'''
<div class="list-heading"><div><h1>Termo com vários bens</h1><p>Um termo e um aceite só para todos os bens que estão com a mesma pessoa, como notebook, monitor e teclado.</p></div></div>{% include 'op_tabs' %}{% include 'op_erros' %}
<section class="panel"><form method="get" class="registry-toolbar"><div class="field"><label for="kit-resp">Responsável</label><select id="kit-resp" name="responsavel"><option value="">Selecione a pessoa</option>{% for nome,qtd in responsaveis %}<option value="{{ nome }}" {{ 'selected' if nome==responsavel }}>{{ nome }} ({{ qtd }} {{ 'bem' if qtd==1 else 'bens' }})</option>{% endfor %}</select></div><button class="btn primary">Ver bens</button></form><p class="hint">A lista mostra quem tem bens ativos sob sua responsabilidade no cadastro. Para mudar o responsável de um bem, use Movimentações.</p></section>
{% if responsavel %}<section class="form-section registry-form op-entry-form"><h2>Bens com {{ responsavel }}</h2>
{% if bens_kit %}<form method="post">{% include 'op_token' %}<input type="hidden" name="responsavel" value="{{ responsavel }}">
<div class="tablewrap"><table class="kit-tabela"><thead><tr><th class="kit-check"><input type="checkbox" id="kit-todos" aria-label="Marcar todos os bens" checked></th><th>Bem</th><th>Patrimônio</th><th>Número de série</th><th>Local</th><th>Conservação</th></tr></thead><tbody>{% for b in bens_kit %}<tr><td class="kit-check"><input type="checkbox" name="bem_id" value="{{ b.id }}" aria-label="Incluir {{ b.nome }}" {{ 'checked' if not selecionados or b.id in selecionados }}></td><td><strong>{{ b.nome }}</strong><small class="table-sub">{{ b.marca or '' }} {{ b.modelo or '' }}</small></td><td>{{ b.patrimonio }}</td><td>{{ b.serie or '—' }}</td><td>{{ b.local }}{% if b.complemento %}<small class="table-sub">{{ b.complemento }}</small>{% endif %}</td><td>{{ b.conservacao }}</td></tr>{% endfor %}</tbody></table></div>
<p class="kit-contador" id="kit-contador" aria-live="polite"></p>
<div class="fields"><div class="field"><label for="kit-ref">Processo / referência</label><input id="kit-ref" name="referencia" maxlength="200" value="{{ valores.get('referencia','') }}"></div><div class="field wide"><label for="kit-texto">Descrição / finalidade *</label><textarea id="kit-texto" name="justificativa" minlength="10" maxlength="5000" required placeholder="Ex.: Equipamentos de trabalho para as atividades do projeto.">{{ valores.get('justificativa','') }}</textarea></div></div>
<p class="hint">Depois de emitir, use Enviar para aceite: a pessoa recebe um link no e-mail e aceita todos os bens de uma vez.</p>
<div class="dialog-actions"><a class="btn" href="{{ url_for('documentos') }}">Cancelar</a><button class="btn primary">Emitir termo</button></div></form>
<script>(function(){const todos=document.getElementById('kit-todos');const caixas=[...document.querySelectorAll('input[name=bem_id]')];const cont=document.getElementById('kit-contador');function atualizar(){const n=caixas.filter(c=>c.checked).length;cont.textContent=n+(n===1?' bem selecionado':' bens selecionados')+' para este termo.';todos.checked=n===caixas.length;todos.indeterminate=n>0&&n<caixas.length;}todos.addEventListener('change',()=>{caixas.forEach(c=>c.checked=todos.checked);atualizar();});caixas.forEach(c=>c.addEventListener('change',atualizar));atualizar();})();</script>
{% else %}<p class="list-empty">Nenhum bem ativo com este responsável.</p>{% endif %}</section>{% endif %}''',
'doc_detalhe': r'''
<div class="op-no-print"><a class="back" href="{{ url_for('documentos') }}">← Termos e documentos</a><div class="list-heading"><div><h1>DOC-{{ '%06d'|format(doc.id) }}</h1><p>{{ doc.tipo }}</p></div><button class="btn primary" type="button" onclick="window.print()">Imprimir / salvar PDF</button></div></div>
{% include 'tdoc_artigo' %}
<section class="panel op-section op-no-print"><h2>Assinatura do emitente</h2>
{% if assinatura %}<div class="op-aceite-status ok"><strong>Assinado eletronicamente por {{ assinatura.nome }} em {{ assinatura.assinado_em|datahora }}</strong><p>A assinatura já aparece no documento impresso, no lugar da linha do emitente.</p></div>
{% elif pode_assinar %}<p class="hint">Confira o documento acima. Para assinar, marque a declaração e digite de novo a sua senha do Patrimônio Carajás: assim o sistema confirma que é você mesmo.</p><form method="post" action="{{ url_for('assinar_documento',documento_id=doc.id) }}" class="tdoc-assinar-form"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><label class="atesto"><input type="checkbox" name="atesto" value="sim" required><span>{{ declaracao_emitente }}</span></label><div class="field"><label for="assinar-senha">Sua senha</label><input id="assinar-senha" type="password" name="senha" required maxlength="512" autocomplete="current-password"></div><div><button class="btn primary">Assinar eletronicamente</button></div></form>
{% else %}<p class="hint">Este documento ainda não foi assinado. Só quem emitiu ({{ doc.autor_nome }}) ou um Administrador pode assinar.</p>{% endif %}</section>
{% if aceita_eletronico %}<section class="panel op-section op-no-print op-aceite"><h2>Aceite eletrônico</h2>
{% if aceite_ok %}<div class="op-aceite-status ok"><strong>Termo aceito em {{ aceite_ok.respondido_em|datahora }}</strong><p>{{ aceite_ok.nome_digitado }} · {{ aceite_ok.email }}. O aceite já aparece no termo impresso, no lugar da assinatura do recebedor.</p></div>
{% else %}{% if aceite_pendente %}<div class="op-aceite-status"><strong>Aguardando o aceite de {{ aceite_pendente.email }}</strong><p>Link enviado em {{ aceite_pendente.criado_em|datahora }} por {{ aceite_pendente.enviado_por_nome }}. Válido até {{ aceite_pendente.expira_data|datahora }}.{% if aceite_pendente.visualizado_em %} Aberto pelo destinatário em {{ aceite_pendente.visualizado_em|datahora }}.{% else %} Ainda não aberto.{% endif %}</p>{% if not usuario.leitura %}<form method="post" action="{{ url_for('cancelar_aceite',documento_id=doc.id) }}"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><button class="btn">Cancelar link</button></form>{% endif %}</div>{% else %}<p class="hint">O responsável recebe um link pessoal no e-mail, lê o termo pelo celular ou computador e confirma o aceite, sem precisar de login. Vale por 7 dias e funciona uma única vez.</p>{% endif %}
{% if not usuario.leitura %}<form method="post" action="{{ url_for('enviar_aceite',documento_id=doc.id) }}" class="op-aceite-form"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><div class="field"><label for="aceite-nome">Nome do responsável</label><input id="aceite-nome" name="nome" maxlength="160" required value="{{ aceite_pendente.nome_destinatario if aceite_pendente else aceite_nome_sugerido }}"></div><div class="field"><label for="aceite-email">E-mail para receber o termo</label><input id="aceite-email" name="email" type="email" maxlength="254" required value="{{ aceite_pendente.email if aceite_pendente else aceite_email_sugerido }}"></div><button class="btn primary">{{ 'Reenviar link' if aceite_pendente or aceites else 'Enviar para aceite' }}</button></form>{% if aceite_pendente %}<small class="hint">Reenviar gera um novo link e invalida o anterior.</small>{% endif %}{% endif %}{% endif %}
{% if aceites %}<details class="op-aceite-historico"{{ ' open' if not aceite_ok }}><summary>Histórico de envios ({{ aceites|length }})</summary><ul class="op-attachments">{% for a in aceites %}<li><span><strong>ACE-{{ '%06d'|format(a.id) }} · {{ a.email }}</strong><small>Enviado em {{ a.criado_em|datahora }} por {{ a.enviado_por_nome }}{% if a.respondido_em %} · respondido em {{ a.respondido_em|datahora }}{% endif %}{% if a.motivo_recusa %} · motivo: {{ a.motivo_recusa }}{% endif %}</small></span><span class="badge {{ 'warn' if a.situacao != 'Aceito' }}">{{ a.situacao }}</span></li>{% endfor %}</ul></details>{% endif %}
</section>{% endif %}
<section class="panel op-section op-no-print"><h2>Anexos e comprovantes</h2><ul class="op-attachments">{% for a in anexos %}<li><a href="{{ url_for('baixar_anexo',anexo_id=a.id) }}">{{ a.nome }}</a><small>{{ a.criado_em|datahora }}</small></li>{% else %}<li>Nenhum comprovante anexado.</li>{% endfor %}</ul>{% if not usuario.leitura %}<form method="post" enctype="multipart/form-data" action="{{ url_for('anexar_documento',documento_id=doc.id) }}"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><div class="field"><label for="doc-anexo">Anexar documento assinado ou comprovante</label><input id="doc-anexo" type="file" name="arquivo" accept="application/pdf,.pdf,image/jpeg,image/png,image/webp,image/heic,image/heif,image/avif,.heic,.heif,.avif" required><small>PDF ou foto JPEG, PNG, WebP, HEIC/HEIF ou AVIF. Até 5 MB por arquivo; máximo de dez anexos. Arquivos ficam salvos no banco.</small></div><div class="dialog-actions"><button class="btn">Anexar arquivo</button></div></form>{% endif %}</section>''',
'baixa_lista': r'''
<div class="list-heading"><div><h1>Encerramento e baixa</h1><p>Organize os processos de saída definitiva e preserve o histórico do patrimônio.</p></div></div>{% include 'enc_tabs' %}<div class="op-actions">{% if not usuario.leitura %}<a class="btn primary" href="{{ url_for('baixas',aba='cadastro') }}">Solicitar baixa</a>{% endif %}</div><section class="panel"><form method="get" class="registry-toolbar"><div class="field"><label for="baixa-q">Pesquisar processo / titular</label><input id="baixa-q" name="q" maxlength="120" value="{{ q }}"></div><div class="field"><label for="baixa-status">Situação</label><select id="baixa-status" name="status"><option value="">Todas</option>{% for st in ['Em análise','Concluída','Indeferida','Cancelada'] %}<option {{ 'selected' if filtro==st }}>{{ st }}</option>{% endfor %}</select></div><button class="btn primary">Pesquisar</button></form><div class="tablewrap"><table><thead><tr><th>Registro / bem</th><th>Motivo</th><th>Processo</th><th>Situação</th><th></th></tr></thead><tbody>{% for p in rows %}<tr><td><strong>BAI-{{ '%06d'|format(p.id) }}</strong><small class="table-sub">{{ p.retrato.nome }}</small></td><td>{{ p.motivo }}</td><td>{{ p.processo }}</td><td><span class="badge {{ 'warn' if p.status=='Em análise' }}">{{ p.status }}</span></td><td><a class="text-action" href="{{ url_for('baixa_detalhe',baixa_id=p.id) }}">Abrir</a></td></tr>{% else %}<tr><td colspan="5" class="list-empty">Nenhum processo encontrado.</td></tr>{% endfor %}</tbody></table></div>{% include 'op_paginacao' %}</section>''',
'baixa_form': r'''
<div class="list-heading"><div><h1>Solicitar encerramento / baixa</h1><p>Registre a análise e reúna os documentos antes da conclusão.</p></div></div>{% include 'op_tabs' %}{% include 'op_erros' %}{% include 'op_busca_bem' %}
<section class="form-section registry-form op-entry-form"><h2>Informações do processo</h2><form method="post">{% include 'op_token' %}<input type="hidden" name="bem_id" value="{{ bem_escolhido.id }}"><p class="op-selection-hint" id="op-selection-hint" {% if bem_escolhido %}hidden{% endif %}>Selecione o bem acima para preencher e salvar este registro.</p><fieldset class="op-data-fields" {% if not bem_escolhido %}disabled{% endif %}><div class="fields"><div class="field"><label for="baixa-motivo">Motivo / finalidade do processo *</label><select id="baixa-motivo" name="motivo" required><option value="">Selecione uma opção</option>{% for grupo,motivos in grupos_motivos_baixa %}<optgroup label="{{ grupo }}">{% for m in motivos %}<option value="{{ m }}" {{ 'selected' if valores.get('motivo')==m }}>{{ m }}</option>{% endfor %}</optgroup>{% endfor %}</select><small>A classificação de inservibilidade depende de avaliação. Doação e transferência são destinações propostas, sujeitas à autorização.</small></div>{% for campo,label,limite in [('processo','Processo administrativo *',200),('titularidade','Titular / proprietário do bem *',160),('destinacao','Destinação proposta *',300),('avaliacao','Referência da avaliação / comissão',300)] %}<div class="field"><label for="baixa-{{ campo }}">{{ label }}</label><input id="baixa-{{ campo }}" name="{{ campo }}" maxlength="{{ limite }}" {{ 'required' if campo!='avaliacao' }} value="{{ valores.get(campo,'') }}"></div>{% endfor %}<div class="field wide"><label for="baixa-just">Justificativa *</label><textarea id="baixa-just" name="justificativa" minlength="10" maxlength="5000" required>{{ valores.get('justificativa','') }}</textarea></div></div><p class="hint">Abertura do processo não gera baixa. Bem ocioso ou recuperável pode ser reaproveitado; doação, transferência e destinação ambiental dependem de avaliação e autorização. Extravio, furto ou roubo exigem apuração. Informe a destinação pretendida no campo acima. <a class="content-link" href="https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2025/decreto/d12785.htm" target="_blank" rel="noopener" style="color:#1769aa;text-decoration:underline">Consultar Decreto nº 12.785/2025</a></p><div class="dialog-actions"><a class="btn" href="{{ url_for('baixas') }}">Cancelar</a><button class="btn primary">Abrir processo</button></div></fieldset></form></section>''',
'baixa_detalhe': r'''
<a class="back" href="{{ url_for('baixas') }}">← Encerramento e baixa</a><div class="list-heading"><div><h1>BAI-{{ '%06d'|format(processo.id) }}</h1><p>{{ processo.retrato.nome }} · {{ processo.processo }}</p></div><span class="badge">{{ processo.status }}</span></div><section class="panel"><h2>Dados da solicitação</h2><dl class="compact-facts">{% for label,key in [('Motivo','motivo'),('Justificativa','justificativa'),('Titular / proprietário','titularidade'),('Destinação proposta','destinacao'),('Avaliação / comissão','avaliacao'),('Decisão','decisao'),('Autoridade','autoridade'),('Autorização / decisão','autorizacao')] %}{% if processo[key] %}<div><dt>{{ label }}</dt><dd>{{ processo[key] }}</dd></div>{% endif %}{% endfor %}</dl><div class="op-actions"><a class="btn" href="{{ url_for('ficha',bem_id=processo.bem_id,consulta=1) }}">Consultar bem</a>{% if solicitacao %}<a class="btn" href="{{ url_for('documento_detalhe',documento_id=solicitacao.id) }}">Solicitação e comprovantes</a>{% endif %}{% if documento %}<a class="btn primary" href="{{ url_for('documento_detalhe',documento_id=documento.id) }}">Registro de conclusão</a>{% endif %}</div></section>
{% if processo.status=='Em análise' and usuario.perfil=='Administrador' %}<section class="form-section registry-form op-section"><h2>Registrar decisão</h2><p>Anexe os documentos de suporte na solicitação. A conclusão exige a referência da autorização e a confirmação do procedimento competente.</p><form method="post" action="{{ url_for('decidir_baixa',baixa_id=processo.id) }}"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><div class="fields"><div class="field"><label for="decisao-acao">Ação *</label><select name="acao" id="decisao-acao"><option value="concluir">Concluir encerramento / baixa</option><option value="indeferir">Indeferir solicitação</option><option value="cancelar">Cancelar processo</option></select></div><div class="field"><label for="decisao-autoridade">Autoridade competente *</label><input id="decisao-autoridade" name="autoridade" required maxlength="160"></div><div class="field wide"><label for="decisao-ref">Documento de decisão / autorização *</label><input id="decisao-ref" name="autorizacao" required maxlength="300"></div><div class="field wide"><label for="decisao-texto">Decisão / fundamentação *</label><textarea id="decisao-texto" name="decisao" required minlength="10" maxlength="5000"></textarea></div></div><label class="op-check"><input type="checkbox" name="confirmar" value="sim"> Para concluir a baixa, confirmo a titularidade, o procedimento documentado e a autorização da autoridade competente.</label><div class="dialog-actions"><button class="btn primary">Registrar decisão</button></div></form></section>{% endif %}''',
'inv_lista': r'''
<div class="list-heading"><div><h1>Inventários anteriores</h1><p>Planeje a conferência física e acompanhe as divergências do patrimônio.</p></div></div><div class="op-actions"><a class="btn" href="{{ url_for('inventario') }}">← Inventário atual</a>{% if not usuario.leitura %}<a class="btn primary" href="{{ url_for('inventario',aba='cadastro') }}">+ Novo inventário</a>{% endif %}</div><section class="panel"><div class="tablewrap"><table><thead><tr><th>Inventário</th><th>Escopo</th><th>Abertura</th><th>Situação</th><th></th></tr></thead><tbody>{% for i in rows %}<tr><td><strong>INV-{{ '%06d'|format(i.id) }}</strong><small class="table-sub">{{ i.nome }}</small></td><td>{{ i.local }}</td><td>{{ i.criado_em|datahora }}</td><td><span class="badge">{{ i.status }}</span></td><td><a class="text-action" href="{{ url_for('inventario_detalhe',inventario_id=i.id) }}">Abrir</a></td></tr>{% else %}<tr><td colspan="5" class="list-empty">Nenhum inventário aberto ou encerrado.</td></tr>{% endfor %}</tbody></table></div>{% include 'op_paginacao' %}</section>''',
'inv_form': r'''
<div class="list-heading"><div><h1>Novo inventário</h1><p>Defina o escopo da conferência. Um inventário pode ficar aberto por vez.</p></div></div>{% include 'op_tabs' %}{% include 'op_erros' %}<section class="form-section registry-form"><h2>Dados do inventário</h2><form method="post">{% include 'op_token' %}<div class="fields"><div class="field wide"><label for="inv-nome">Nome do inventário *</label><input id="inv-nome" name="nome" required maxlength="160" value="{{ valores.get('nome','') }}" placeholder="Ex.: Conferência patrimonial · outubro de 2026"></div><div class="field"><label for="inv-base">Local da conferência</label><select id="inv-base" name="base_id"><option value="">Todos os locais</option>{% for b in bases_destino %}<option value="{{ b.id }}" {{ 'selected' if valores.get('base_id')|string==b.id|string }}>{{ b.nome }}</option>{% endfor %}</select></div><div class="field"><label for="inv-convenio">Convênio (opcional)</label><select id="inv-convenio" name="convenio_id"><option value="">Todos os convênios</option>{% for c in convenios_inventario %}<option value="{{ c.id }}" {{ 'selected' if valores.get('convenio_id')|string==c.id|string }}>{{ c.nome }}</option>{% endfor %}</select><small>Use para conferir só os bens de um convênio, por exemplo no encerramento.</small></div><div class="field"><label for="inv-ref">Documento de referência (opcional)</label><input id="inv-ref" name="referencia" maxlength="200" value="{{ valores.get('referencia','') }}"><small>Informe a portaria ou o processo SEI, se houver.</small></div></div><div class="fields"><div class="field"><label for="inv-prazo">Prazo para concluir o inventário</label><input id="inv-prazo" name="prazo" type="date" value="{{ valores.get('prazo','') }}"><small>Opcional. O prazo ficará nos dados do inventário.</small></div><div class="field"><label for="inv-comissao">Comissão / equipe responsável</label><textarea id="inv-comissao" name="comissao" maxlength="1000" placeholder="Informe os nomes da comissão ou equipe">{{ valores.get('comissao','') }}</textarea><small>Cada conferência registra o usuário responsável e a data.</small></div></div><p class="hint">O inventário guarda os bens e seus dados na abertura. A conferência não altera automaticamente local, responsável ou baixa.</p><div class="dialog-actions"><a class="btn" href="{{ url_for('inventario') }}">Cancelar</a><button class="btn primary">Abrir conferência</button></div></form></section>''',
'inv_detalhe': r'''
{% set total_inv=resumo.values()|sum %}{% set pendentes=resumo.get('Pendente',0) %}{% set conferidos_inv=resumo.get('Conferido',0) %}{% set ocorrencias_inv=resumo.get('Divergência',0)+resumo.get('Não localizado',0) %}{% set verificados=total_inv-pendentes %}{% set progresso=verificados/total_inv*100 if total_inv else 0 %}{% set pode_conferir=inv.status=='Aberto' and not usuario.leitura %}
{% macro resultado(item) %}<span class="inv30-badge {{ 'pending' if item.status=='Pendente' else 'checked' if item.status=='Conferido' else 'occurrence' }}">{{ icon('check' if item.status=='Conferido' else 'clock') }}{{ item.status }}</span>{% endmacro %}
{% macro acoes(item) %}{% if item.status=='Pendente' and pode_conferir %}<a class="btn inv30-occurrence" href="{{ url_for('conferir_inventario',item_id=item.id,ocorrencia='sim',**retorno_args) }}#inv-obs" aria-label="Registrar ocorrência de {{ item.retrato.nome }}" title="Registrar ocorrência"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M12 3 2 21h20L12 3Z"/><path d="M12 9v5m0 3v1"/></svg></a><a class="btn primary inv30-conferir" href="{{ url_for('conferir_inventario',item_id=item.id,**retorno_args) }}">{{ icon('check') }}Conferir</a>{% else %}<button type="button" class="btn" data-inv30-record="{{ dict(nome=item.retrato.nome,status=item.status,autor=item.conferente_nome or 'Não informado',quando=item.conferido_em|datahora,observacao=item.observacao or 'Sem observações.',ficha=url_for('ficha',bem_id=item.bem_id,consulta=1),revisar=url_for('conferir_inventario',item_id=item.id,**retorno_args) if pode_conferir else '')|tojson|forceescape }}">Ver registro</button>{% endif %}{% endmacro %}
<div class="inv30-page">
<header class="inv30-heading"><div><div class="inv30-title"><h1>Inventário {{ inv.nome }}</h1><span class="inv30-badge {{ 'checked' if inv.status=='Aberto' else 'closed' }}">{{ inv.status }}</span></div><p>INV-{{ '%06d'|format(inv.id) }} · {{ inv.local }}</p></div><div class="inv30-heading-actions">{% if not usuario.leitura %}<a class="btn inv301-new" href="{{ url_for('inventario',aba='cadastro') }}"><span aria-hidden="true">＋</span>Novo inventário</a>{% endif %}<a class="btn" href="{{ url_for('inventario',aba='anteriores') }}">{{ icon('clock') }}Histórico</a><a class="btn" id="inv30-report" href="{{ link_relatorio }}" target="_blank" rel="noopener">{{ icon('doc') }}Relatório PDF</a>{% if pode_conferir %}<button type="button" class="btn primary inv30-qr-top" data-inventory-scan>{{ icon('scan') }}Conferir com QR Code</button>{% endif %}</div></header>
<section class="inv30-progress" aria-label="Progresso e dados do inventário"><div class="inv30-progress-summary"><div class="inv30-ring" role="img" aria-label="{{ progresso|int }}% verificados, incluindo ocorrências"><svg viewBox="0 0 80 80" aria-hidden="true"><circle cx="40" cy="40" r="32"/><circle class="inv30-ring-value" cx="40" cy="40" r="32" pathLength="100" stroke-dasharray="{{ progresso }} 100" transform="rotate(-90 40 40)"/></svg><strong>{{ progresso|int }}%</strong></div><div><small>Progresso da conferência</small><h2>{{ verificados }} de {{ total_inv }} bens</h2><p>faltam {{ pendentes }} · {{ ocorrencias_inv }} {{ 'ocorrência' if ocorrencias_inv==1 else 'ocorrências' }}</p></div></div><div class="inv30-progress-detail"><dl><div><dt>Abertura</dt><dd>{{ inv.criado_em|datahora }}</dd></div><div><dt>Prazo</dt><dd>{{ inv.prazo.strftime('%d/%m/%Y') if inv.prazo else 'Não informado' }}{% if inv.prazo and inv.status=='Aberto' %}{% if inv.prazo==hoje_local() %}<span class="inv30-deadline today">hoje</span>{% elif inv.prazo<hoje_local() %}<span class="inv30-deadline overdue">vencido</span>{% endif %}{% endif %}</dd></div><div><dt>Referência</dt><dd>{{ inv.referencia or 'Não informada' }}</dd></div><div><dt>Equipe</dt><dd>{{ inv.comissao or 'Não informada' }}</dd></div></dl><div class="inv30-segments" role="img" aria-label="{{ conferidos_inv }} conferidos, {{ pendentes }} pendentes e {{ ocorrencias_inv }} ocorrências"><span class="checked" style="width:{{ conferidos_inv/total_inv*100 if total_inv else 0 }}%"></span><span class="pending" style="width:{{ pendentes/total_inv*100 if total_inv else 0 }}%"></span><span class="occurrence" style="width:{{ ocorrencias_inv/total_inv*100 if total_inv else 0 }}%"></span></div><div class="inv30-legend"><span><i class="checked"></i>Conferidos {{ conferidos_inv }}</span><span><i class="pending"></i>Pendentes {{ pendentes }}</span><span><i class="occurrence"></i>Ocorrências {{ ocorrencias_inv }}</span></div></div></section>
{% if not usuario.leitura %}<section class="panel campo-painel" id="equipe-campo"><div class="campo-painel-cab"><div><h2>Equipe de campo · sem internet</h2><p>Gere um link e envie pelo WhatsApp. A pessoa abre uma vez com internet, confere os bens pela câmera mesmo sem sinal, e tudo é enviado sozinho quando a internet voltar. Não precisa de login.</p></div></div>
{% if links_campo %}<ul class="campo-links">{% for l in links_campo %}<li><div><strong>{{ l.rotulo or 'Equipe de campo' }}</strong><small>{{ l.local or 'Todos os locais deste inventário' }} · {{ 'vencido em' if l.vencido else 'válido até' }} {{ l.expira_data|datahora }} · {{ l.envios }} {{ 'envio' if l.envios==1 else 'envios' }}{% if l.ultimo_envio %} · último em {{ l.ultimo_envio|datahora }}{% endif %}</small></div><form method="post" action="{{ url_for('desativar_link_campo',link_id=l.id) }}"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><button class="btn">Desativar</button></form></li>{% endfor %}</ul>{% endif %}
{% if inv.status=='Aberto' %}<form method="post" action="{{ url_for('criar_link_campo',inventario_id=inv.id) }}" class="campo-form"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><div class="field"><label for="campo-rotulo">Nome da equipe</label><input id="campo-rotulo" name="rotulo" maxlength="120" placeholder="Ex.: Equipe Base Gavião Real"></div><div class="field"><label for="campo-local">Local que a equipe vai conferir</label><select id="campo-local" name="local"><option value="">Todos os locais deste inventário</option>{% for l in inv_locais %}<option value="{{ l }}">{{ l }}</option>{% endfor %}</select></div><div class="field"><label for="campo-validade">Validade do link</label><select id="campo-validade" name="dias">{% for d in [1,3,7,15,30] %}<option value="{{ d }}" {{ 'selected' if d==7 }}>{{ d }} {{ 'dia' if d==1 else 'dias' }}</option>{% endfor %}</select></div><button class="btn primary">Gerar link para a equipe</button></form>{% endif %}
{% if achados_campo %}<details class="campo-achados" open><summary>Encontrados fora da lista ({{ achados_campo|length }})</summary><p class="hint">Bens que a equipe encontrou e que não estão neste inventário: sem plaqueta, de outro local ou ainda não cadastrados. Cadastre ou movimente conforme o caso.</p><ul>{% for a in achados_campo %}<li><strong>{{ a.descricao }}</strong><small>{% if a.codigo %}Código lido: {{ a.codigo }} · {% endif %}{{ a.pessoa }} · {{ a.criado_em|datahora }}</small></li>{% endfor %}</ul></details>{% endif %}
</section>{% endif %}
<section class="inv30-list"><div class="inv30-toolbar"><nav class="inv30-tabs" id="inv30-tabs" aria-label="Filtrar bens por resultado">{% for chave,label,n,status_tab,occ_tab in [('todos','Todos',total_inv,'',''),('pendentes','Pendentes',pendentes,'Pendente',''),('conferidos','Conferidos',conferidos_inv,'Conferido',''),('ocorrencias','Ocorrências',ocorrencias_inv,'','sim')] %}{% set selected=(chave=='ocorrencias' and request.args.get('ocorrencias')=='sim') or (not request.args.get('ocorrencias') and ((chave=='todos' and not filtro) or (status_tab and filtro==status_tab))) %}<a data-inv30-filter href="{{ url_for('inventario_detalhe',inventario_id=inv.id,q=q,local=local_filtro,status=status_tab,ocorrencias=occ_tab) }}" class="{{ 'selected' if selected }}" {% if selected %}aria-current="true"{% endif %}>{{ label }}<span>{{ n }}</span></a>{% endfor %}</nav><form method="get" class="inv30-filters" id="inv30-filters"><input type="hidden" name="status" value="{{ filtro }}"><input type="hidden" name="ocorrencias" value="{{ request.args.get('ocorrencias','') }}"><label class="visually-hidden" for="inv30-local">Local dos bens</label><select name="local" id="inv30-local"><option value="">Todos os locais</option>{% for l in inv_locais %}<option value="{{ l }}" {{ 'selected' if local_filtro==l }}>{{ l }}</option>{% endfor %}</select><label class="visually-hidden" for="inv30-search">Nome, série ou patrimônio</label><input id="inv30-search" name="q" type="search" maxlength="120" value="{{ q }}" placeholder="Nome, série ou patrimônio" autocomplete="off"><noscript><button class="btn" type="submit">Aplicar filtros</button></noscript></form></div><p id="inv30-filter-status" class="inv30-filter-status" role="status" aria-live="polite"></p>
<div id="inv30-results" data-matches="{{ quantidade_operacao }}"><div class="tablewrap inv30-table-wrap"><table class="inv30-table"><thead><tr><th>Bem</th><th>Identificação</th><th>Base / ambiente</th><th>Resultado</th><th>Ação</th></tr></thead><tbody>{% for item in rows %}<tr class="{{ 'is-checked' if item.status=='Conferido' }}"><td><div class="inv30-asset"><div class="inv30-photo">{% if fotos.get(item.bem_id) %}<img loading="lazy" src="{{ url_for('foto_bem',bem_id=item.bem_id) }}" alt="Foto de {{ item.retrato.nome }}" width="48" height="48">{% else %}{{ icon('camera') }}{% endif %}</div><div><strong>{{ item.retrato.nome }}</strong>{% if not fotos.get(item.bem_id) %}<small>sem foto</small>{% endif %}</div></div></td><td class="inv30-identification"><strong>{{ item.retrato.numero_ngi or item.retrato.plaqueta_original or 'Sem plaqueta' }}</strong><small>Série {{ item.retrato.serie or 'não informada' }}</small></td><td><strong class="inv30-location">{{ item.retrato.local }}</strong><small class="inv30-room">{{ item.retrato.complemento or 'Ambiente não informado' }}</small></td><td>{{ resultado(item) }}</td><td><div class="inv30-row-actions">{{ acoes(item) }}</div></td></tr>{% else %}<tr><td colspan="5" class="inv30-empty">Nenhum bem encontrado com estes filtros.</td></tr>{% endfor %}</tbody></table></div>
<div class="inv30-mobile-cards">{% for item in rows %}<article class="{{ 'is-checked' if item.status=='Conferido' }}"><div class="inv30-asset"><div class="inv30-photo">{% if fotos.get(item.bem_id) %}<img loading="lazy" width="48" height="48" src="{{ url_for('foto_bem',bem_id=item.bem_id) }}" alt="Foto de {{ item.retrato.nome }}">{% else %}{{ icon('camera') }}{% endif %}</div><div><strong>{{ item.retrato.nome }}</strong>{% if not fotos.get(item.bem_id) %}<small>sem foto</small>{% endif %}</div></div><p class="inv30-identification">{{ item.retrato.numero_ngi or item.retrato.plaqueta_original or 'Sem plaqueta' }}<small>Série {{ item.retrato.serie or 'não informada' }}</small></p><p>{{ item.retrato.local }} · {{ item.retrato.complemento or 'Ambiente não informado' }}</p>{{ resultado(item) }}<div class="inv30-row-actions">{{ acoes(item) }}</div></article>{% else %}<p class="inv30-empty">Nenhum bem encontrado.</p>{% endfor %}</div>{% if paginas_operacao>1 %}<div class="inv30-pagination">{% include 'op_paginacao' %}</div>{% endif %}
<footer class="inv30-list-footer"><span>{{ total_inv }} bens neste inventário{% if quantidade_operacao!=total_inv %} · {{ quantidade_operacao }} nesta seleção{% endif %}</span>{% if inv.status=='Aberto' %}{% if pendentes %}<span>Ao concluir os {{ total_inv }} bens, o botão <strong>Encerrar inventário</strong> é liberado.</span>{% elif usuario.perfil=='Administrador' %}<button class="btn primary" type="button" data-inv30-close>Encerrar inventário</button>{% else %}<span>Conferência concluída. O encerramento é realizado pelo administrador.</span>{% endif %}{% else %}<span>Inventário encerrado · resultados preservados.</span>{% endif %}</footer></div></section>
{% if pode_conferir %}<div class="inv30-mobile-qr"><button class="btn primary" type="button" data-inventory-scan>{{ icon('scan') }}Conferir com QR Code</button></div>{% endif %}
<dialog id="inv30-record" class="inv30-dialog" aria-labelledby="inv30-record-title"><div class="inv30-dialog-heading"><h2 id="inv30-record-title">Registro de conferência</h2><button type="button" class="btn" data-inv30-dismiss>Fechar</button></div><h3 id="inv30-record-name"></h3><dl><dt>Resultado</dt><dd id="inv30-record-status"></dd><dt>Conferente</dt><dd id="inv30-record-author"></dd><dt>Data e hora</dt><dd id="inv30-record-date"></dd><dt>Observações</dt><dd id="inv30-record-notes"></dd></dl><div class="inv30-dialog-actions"><a class="btn" id="inv30-record-asset">Ver ficha do bem</a><a class="btn primary" id="inv30-record-review">Revisar conferência</a></div></dialog>
{% if inv.status=='Aberto' and usuario.perfil=='Administrador' %}<dialog id="inv30-close" class="inv30-dialog" aria-labelledby="inv30-close-title"><div class="inv30-dialog-heading"><h2 id="inv30-close-title">Encerrar inventário</h2><button class="btn" type="button" data-inv30-dismiss>Voltar</button></div><p>Confirme a conclusão da conferência. Os resultados e as ocorrências serão preservados.</p><form method="post" action="{{ url_for('encerrar_inventario',inventario_id=inv.id) }}"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><label class="op-check"><input type="checkbox" name="confirmar" value="sim" required> Confirmo a conclusão da conferência e o registro das pendências.</label><button class="btn primary" type="submit">Confirmar encerramento</button></form></dialog>{% endif %}
</div>
<script>
(()=>{const root=document.querySelector('.inv30-page'),form=document.getElementById('inv30-filters'),search=document.getElementById('inv30-search'),local=document.getElementById('inv30-local'),status=document.getElementById('inv30-filter-status');let timer,controller,seq=0,composing=false,invoker;
async function update(raw,push=false){clearTimeout(timer);const url=new URL(raw,location.origin);if(url.origin!==location.origin)return;controller?.abort();controller=new AbortController();const turn=++seq;document.getElementById('inv30-results').setAttribute('aria-busy','true');status.textContent='Atualizando bens…';try{const response=await fetch(url.pathname+url.search,{signal:controller.signal,headers:{'X-Requested-With':'XMLHttpRequest'}});if(turn!==seq)return;if(response.redirected){location.assign(response.url);return;}if(!response.ok)throw new Error();const doc=new DOMParser().parseFromString(await response.text(),'text/html');if(turn!==seq)return;const next=doc.getElementById('inv30-results'),tabs=doc.getElementById('inv30-tabs');if(!next||!tabs){location.assign(url.pathname+url.search);return;}document.getElementById('inv30-results').replaceWith(next);document.getElementById('inv30-tabs').replaceWith(tabs);const report=doc.getElementById('inv30-report');if(report)document.getElementById('inv30-report').href=report.getAttribute('href');form.elements.status.value=url.searchParams.get('status')||'';form.elements.ocorrencias.value=url.searchParams.get('ocorrencias')||'';search.value=url.searchParams.get('q')||'';local.value=url.searchParams.get('local')||'';history[push?'pushState':'replaceState']({},'',url.pathname+url.search);status.textContent=next.dataset.matches+' bens encontrados.';}catch(error){if(error.name!=='AbortError'&&turn===seq)status.textContent='Não foi possível atualizar. Tente novamente ou pressione Enter na busca.';}finally{if(turn===seq)document.getElementById('inv30-results')?.removeAttribute('aria-busy');}}
function filter(push=false){const url=new URL(location.href);url.search='';for(const [key,value] of new FormData(form))if(String(value).trim())url.searchParams.set(key,String(value).trim());update(url,push);}
form.addEventListener('submit',e=>{e.preventDefault();filter(true);});local.addEventListener('change',()=>filter(true));search.addEventListener('compositionstart',()=>{composing=true;clearTimeout(timer);});search.addEventListener('compositionend',()=>{composing=false;clearTimeout(timer);timer=setTimeout(()=>filter(),350);});search.addEventListener('input',()=>{if(composing)return;clearTimeout(timer);controller?.abort();seq++;timer=setTimeout(()=>filter(),350);});
root.addEventListener('click',e=>{const link=e.target.closest('[data-inv30-filter],.inv30-pagination .pagination a');if(link&&!e.ctrlKey&&!e.metaKey&&!e.shiftKey&&!e.altKey){e.preventDefault();const target=new URL(link.href);if(link.hasAttribute('data-inv30-filter')){for(const [key,value] of [['q',search.value.trim()],['local',local.value]]){if(value)target.searchParams.set(key,value);else target.searchParams.delete(key);}}update(target,true);return;}const record=e.target.closest('[data-inv30-record]');if(record){const data=JSON.parse(record.dataset.inv30Record);for(const [id,key] of [['name','nome'],['status','status'],['author','autor'],['date','quando'],['notes','observacao']])document.getElementById('inv30-record-'+id).textContent=data[key];document.getElementById('inv30-record-asset').href=data.ficha;const review=document.getElementById('inv30-record-review');review.hidden=!data.revisar;review.href=data.revisar||'#';invoker=record;document.getElementById('inv30-record').showModal();}if(e.target.closest('[data-inv30-close]')){invoker=e.target.closest('[data-inv30-close]');document.getElementById('inv30-close')?.showModal();}if(e.target.closest('[data-inv30-dismiss]'))e.target.closest('dialog').close();});root.querySelectorAll('dialog').forEach(d=>d.addEventListener('close',()=>invoker?.focus()));window.addEventListener('popstate',()=>update(location.href));})();
</script>
''',
'inv_item': r'''
<a class="back" href="{{ url_for('inventario_detalhe',inventario_id=inv.id,**retorno_args) }}">← Conferência de inventário</a><div class="list-heading"><div><h1>Conferir bem</h1><p>{{ item.retrato.nome }} · {{ item.retrato.serie or 'Série não informada' }}</p></div></div>{% include 'op_erros' %}<section class="form-section registry-form"><div class="asset-profile-head"><div class="asset-profile-photo">{% if ativo.tem_foto %}<img src="{{ url_for('foto_bem',bem_id=ativo.id) }}" alt="Foto do bem">{% else %}<span>Sem foto</span>{% endif %}</div><div><h2>{{ ativo.nome }}</h2><p>{{ ativo.marca }} · {{ ativo.modelo }} · Série: {{ ativo.serie or 'Não informada' }}</p></div></div><p>{{ ativo.patrimonio }} · Local atual: {{ ativo.local }} · Responsável: {{ ativo.responsavel }}</p><div class="callout"><strong>Dados na abertura</strong><p>{{ item.retrato.local }} · {{ item.retrato.responsavel }} · {{ item.retrato.conservacao }}</p></div><form method="post"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><input type="hidden" name="revisao" value="{{ item.revisao }}"><input type="hidden" name="revisao_bem" value="{{ ativo.revisao }}"><div class="fields"><div class="field wide"><label for="inv-resultado">Resultado *</label><select id="inv-resultado" name="status"><option value="">Selecione o resultado</option>{% for st,label in [('Conferido','Encontrei e os dados conferem'),('Divergência','Encontrei, mas há divergência'),('Não localizado','Não localizei o bem')] %}<option value="{{ st }}" {{ 'selected' if valores.get('status',item.status)==st }}>{{ label }}</option>{% endfor %}</select></div><div class="field wide"><label for="inv-obs">Observações / situação encontrada</label><textarea id="inv-obs" name="observacao" maxlength="3000">{{ valores.get('observacao',item.observacao) }}</textarea><small>Obrigatória para divergência e não localizado. A ausência física não gera baixa automática.</small></div></div><div class="dialog-actions"><a class="btn" href="{{ url_for('inventario_detalhe',inventario_id=inv.id,**retorno_args) }}">Voltar</a><button class="btn primary">Salvar conferência</button></div></form></section><script>(()=>{const s=document.getElementById('inv-resultado'),o=document.getElementById('inv-obs');function atualizar(){o.required=['Divergência','Não localizado'].includes(s.value);o.minLength=o.required?10:0;}s.addEventListener('change',atualizar);atualizar();})();</script>{% if request.args.get('ocorrencia')=='sim' %}<script>(()=>{const result=document.getElementById('inv-resultado');if(result){result.value='Divergência';result.dispatchEvent(new Event('change'));document.getElementById('inv-obs')?.focus();}})();</script>{% endif %}''',
'relatorios': r'''
<div class="list-heading"><div><h1>Relatórios</h1><p>Consulte o patrimônio e as operações com os mesmos filtros na tela e na exportação.</p></div><div class="pdf-btns"><a class="btn" href="{{ link_csv }}">Exportar CSV</a><a class="btn primary" href="{{ link_csv|replace('/relatorios/exportar.csv','/relatorios/operacoes.pdf') }}">Baixar PDF</a></div></div><nav class="registry-navigation" aria-label="Relatórios"><a href="{{ url_for('relatorios') }}" class="{{ 'current' if request.endpoint=='relatorios' }}">Dashboard patrimonial</a><a href="{{ url_for('indicadores_gestao') }}" class="{{ 'current' if request.endpoint=='indicadores_gestao' }}">Indicadores de gestão</a><a href="{{ url_for('relatorio_operacional') }}" class="{{ 'current' if request.endpoint=='relatorio_operacional' }}">Relatório de registros</a></nav>{% include 'op_erros' %}
<section class="panel"><form method="get" class="op-report-filters"><div class="field"><label for="rel-tipo">Relatório</label><select id="rel-tipo" name="tipo">{% for key,label in [('bens','Bens patrimoniais'),('movimentacoes','Movimentações'),('baixas','Encerramento e baixa'),('inventario','Conferências de inventário')] %}<option value="{{ key }}" {{ 'selected' if filtros.tipo==key }}>{{ label }}</option>{% endfor %}</select></div><div class="field"><label for="rel-busca">Bem / série / plaqueta</label><input id="rel-busca" name="q" maxlength="120" value="{{ filtros.q }}"></div><div class="field"><label for="rel-base">Local atual</label><select id="rel-base" name="base_id"><option value="">Todos</option>{% for b in bases_relatorio %}<option value="{{ b.id }}" {{ 'selected' if filtros.base_id==b.id }}>{{ b.nome }}</option>{% endfor %}</select></div><div class="field"><label for="rel-convenio">Convênio atual</label><select id="rel-convenio" name="convenio_id"><option value="">Todos</option>{% for c in convenios_relatorio %}<option value="{{ c.id }}" {{ 'selected' if filtros.convenio_id==c.id }}>{{ c.nome }}</option>{% endfor %}</select></div><div class="field"><label for="rel-acervo">Acervo (relatório de bens)</label><select id="rel-acervo" name="acervo">{% for key,label in [('ativos','Ativos'),('baixados','Baixados'),('todos','Todos')] %}<option value="{{ key }}" {{ 'selected' if filtros.acervo==key }}>{{ label }}</option>{% endfor %}</select></div><div class="field"><label for="rel-status">Situação da operação</label><select id="rel-status" name="status"><option value="">Todas</option>{% for st in (['Pendente','Concluída','Cancelada'] if filtros.tipo=='movimentacoes' else ['Em análise','Concluída','Indeferida','Cancelada'] if filtros.tipo=='baixas' else ['Pendente','Conferido','Divergência','Não localizado'] if filtros.tipo=='inventario' else []) %}<option {{ 'selected' if filtros.status==st }}>{{ st }}</option>{% endfor %}</select></div>{% for campo,label in [('inicio','De'),('fim','Até')] %}<div class="field"><label for="rel-{{ campo }}">{{ label }}</label><input id="rel-{{ campo }}" name="{{ campo }}" type="date" value="{{ filtros[campo] }}"></div>{% endfor %}{% if filtros.inventario_id %}<input type="hidden" name="inventario_id" value="{{ filtros.inventario_id }}">{% endif %}<div class="op-actions"><button class="btn primary">Aplicar filtros</button><a class="btn" href="{{ url_for('relatorios') }}">Limpar</a></div></form><p class="hint">Período: aquisição dos bens, abertura das movimentações e baixas ou data da conferência. Local e convênio usam os vínculos atuais. O valor exibido é o de aquisição, sem depreciação.</p>
<div class="tablewrap"><table><thead><tr>{% for c in colunas %}<th>{{ c }}</th>{% endfor %}</tr></thead><tbody>{% for linha in linhas %}<tr>{% for valor in linha %}<td>{{ valor }}</td>{% endfor %}</tr>{% else %}<tr><td colspan="{{ colunas|length }}" class="list-empty">Nenhum registro encontrado.</td></tr>{% endfor %}</tbody></table></div>{% include 'op_paginacao' %}</section>''',
}
app.jinja_loader = ChoiceLoader([DictLoader(OP_TEMPLATES), app.jinja_loader])

# ============================================================
# APOIO AOS MÓDULOS OPERACIONAIS
# ============================================================
TIPOS_MOVIMENTO = ('Transferência de responsável', 'Remanejamento interno', 'Entrega temporária', 'Manutenção')
GRUPOS_MOTIVOS_BAIXA = (
    ('Avaliação para desfazimento por inservibilidade', (
        'Inservibilidade — ocioso', 'Inservibilidade — recuperável',
        'Inservibilidade — antieconômico', 'Inservibilidade — irrecuperável')),
    ('Destinação proposta', ('Doação', 'Transferência externa',
        'Destinação / disposição final ambientalmente adequada', 'Devolução ao proprietário')),
    ('Ocorrências sujeitas à apuração', ('Extravio', 'Furto / roubo')),
    ('Outra hipótese', ('Outro — justificar no processo',)),
)
MOTIVOS_BAIXA = tuple(m for _, motivos in GRUPOS_MOTIVOS_BAIXA for m in motivos)
STATUS_INVENTARIO = ('Pendente', 'Conferido', 'Divergência', 'Não localizado')


def hoje_local():
    return datetime.now(timezone(timedelta(hours=-3))).date()


@app.template_filter('datahora')
def datahora(valor):
    if not valor:
        return '—'
    if isinstance(valor, datetime):
        if valor.tzinfo is None:
            valor = valor.replace(tzinfo=timezone.utc)
        return valor.astimezone(timezone(timedelta(hours=-3))).strftime('%d/%m/%Y %H:%M')
    return valor.strftime('%d/%m/%Y')


def carregar(modelo, chave, bloquear=False):
    q = select(modelo).where(modelo.id == chave)
    if bloquear:
        q = q.with_for_update().execution_options(populate_existing=True)
    obj = db.session.scalar(q)
    if obj is None:
        abort(404)
    return obj


def inteiro(valor):
    try:
        n = int(valor)
        return n if n > 0 else None
    except (ValueError, TypeError):
        return None


def paginar_operacao(consulta, por_pagina=25):
    total = db.session.scalar(select(func.count()).select_from(consulta.order_by(None).subquery())) or 0
    paginas = max(1, (total + por_pagina - 1)//por_pagina)
    pagina = min(inteiro(request.args.get('pagina')) or 1, paginas)
    rows = db.session.scalars(consulta.limit(por_pagina).offset((pagina-1)*por_pagina)).all()
    args = request.args.to_dict()
    args.pop('pagina', None)
    def url_pagina(n):
        return url_for(request.endpoint, **(request.view_args or {}), **dict(args,pagina=n))
    return dict(rows=rows, quantidade_operacao=total, pagina_operacao=pagina,
        paginas_operacao=paginas, primeiro_operacao=(pagina-1)*por_pagina+1 if total else 0,
        ultimo_operacao=min(pagina*por_pagina,total),
        numeros_operacao=sorted({1,paginas,*range(max(1,pagina-2),min(paginas,pagina+2)+1)}),
        url_operacao_pagina=url_pagina)


def tela_operacao(modulo, template, titulo, status=200, **dados):
    return render_template_string(TEMPLATE, bem=None, formulario=False,
        modulo_page=True, modulo=modulo, modulo_template=template,
        modulo_titulo=titulo,
        op_endpoint={'bens':'listar_bens','movimentacoes':'movimentacoes','documentos':'documentos','baixas':'baixas','inventario':'inventario','relatorios':'relatorios'}[modulo],
        op_lista={'bens':'Bens cadastrados','movimentacoes':'Movimentações registradas','documentos':'Documentos emitidos','baixas':'Processos registrados','inventario':'Inventários registrados','relatorios':'Relatórios'}[modulo],
        op_novo={'bens':'Cadastrar bem','movimentacoes':'Nova movimentação','documentos':'Emitir documento','baixas':'Solicitar baixa','inventario':'Abrir inventário','relatorios':'Relatórios'}[modulo],
        op_form=template.endswith('_form'), **dados, **contexto_painel()), status


def token_operacao():
    if request.method == 'POST':
        return request.form.get('operacao_token','')
    valor = secrets.token_hex(24)
    session['operacoes_tokens'] = session.get('operacoes_tokens',[])[-19:] + [valor]
    return valor


def validar_token_operacao():
    token = request.form.get('operacao_token','')
    anterior = db.session.get(OperacaoPatrimonial,token) if re.fullmatch(r'[a-f0-9]{48}',token) else None
    if anterior and anterior.autor_id == g.usuario.id:
        return redirect(anterior.destino)
    if token not in session.get('operacoes_tokens',[]):
        abort(400,description='Formulário vencido. Abra um novo cadastro nesta aba.')
    if db.engine.dialect.name == 'postgresql':
        db.session.execute(text('SELECT pg_advisory_xact_lock(:chave)'),
            {'chave':int(hashlib.sha256(token.encode()).hexdigest()[:15],16)})
        anterior = db.session.get(OperacaoPatrimonial,token,populate_existing=True)
        if anterior and anterior.autor_id == g.usuario.id:
            return redirect(anterior.destino)
    return None


def finalizar_operacao(destino):
    db.session.add(OperacaoPatrimonial(token=request.form['operacao_token'],autor_id=g.usuario.id,destino=destino))
    db.session.commit()
    return redirect(destino)


def bem_operavel(bem):
    if bem.encerrado:
        raise ValueError('Este bem já foi baixado. O histórico permanece disponível para consulta.')


def trava_bem(bem_id):
    bem = carregar(Bem,bem_id,True)
    bem_operavel(bem)
    return bem


def processo_aberto(bem_id):
    return db.session.scalar(select(ProcessoBaixa).where(ProcessoBaixa.bem_id==bem_id,ProcessoBaixa.status=='Em análise'))


def movimento_pendente(bem_id):
    return db.session.scalar(select(Movimento).where(Movimento.bem_id==bem_id,Movimento.status=='Pendente'))


def entrega_aberta(bem_id):
    return db.session.scalar(select(Movimento).where(Movimento.bem_id==bem_id,
        Movimento.tipo.in_(('Entrega temporária','Manutenção')),Movimento.status=='Concluída',Movimento.devolvido_em.is_(None)))


def criar_documento(tipo,bem,dados,resumo,movimento=None,baixa=None):
    payload = dict(dados)
    payload['bem'] = snapshot(bem)
    payload['emitido_em'] = datetime.now(timezone.utc).isoformat()
    payload['emitido_por'] = g.usuario.nome
    doc = Documento(tipo=tipo,bem_id=bem.id,dados=payload,resumo=resumo,
        integridade=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
        autor_id=g.usuario.id,autor_nome=g.usuario.nome,
        movimento_id=movimento.id if movimento else None,baixa_id=baixa.id if baixa else None)
    db.session.add(doc)
    db.session.flush()
    return doc


def opcoes_bases():
    return db.session.scalars(select(BaseLocal).where(BaseLocal.ativo.is_(True)).order_by(BaseLocal.nome)).all()


@app.get('/api/bens/pesquisa-operacao')
@login_obrigatorio
def pesquisar_bens_operacao():
    if g.usuario.leitura:
        abort(403)
    busca=request.args.get('q','').strip()[:120]
    consulta=select(Bem).where(Bem.encerrado.is_(False))
    origem=request.args.get('origem','')
    if request.args.get('exigir_local')=='sim' and not origem:return jsonify(bens=[],tem_mais=False)
    if origem=='sem_base':consulta=consulta.where(Bem.base_id.is_(None))
    elif origem:
        chave=inteiro(origem)
        if not chave or not db.session.get(BaseLocal,chave):abort(400,description='Local de origem inválido.')
        consulta=consulta.where(Bem.base_id==chave)
    if busca:
        consulta=consulta.where(or_(*(campo.icontains(busca,autoescape=True)
            for campo in (Bem.nome,Bem.serie,Bem.numero_ngi,Bem.plaqueta_original,Bem.marca))))
    bens=db.session.scalars(consulta.order_by(Bem.id.desc()).limit(16)).all()
    return jsonify(bens=[dict(id=b.id,nome=b.nome,patrimonio=b.patrimonio,
        serie=b.serie or b.serie_excecao,local=b.local,endereco=b.endereco,
        responsavel=b.responsavel,convenio=b.convenio,revisao=b.revisao,
        url=url_for('ficha',bem_id=b.id)) for b in bens[:15]],tem_mais=len(bens)>15)


def busca_bem_selecionado():
    # Picker paginado: não carrega 700 bens em uma lista suspensa.
    chave = inteiro(request.values.get('bem_id'))
    selecionado = db.session.get(Bem,chave) if chave else None
    busca = request.args.get('buscar_bem','').strip()[:120]
    resultados=[]
    if busca:
        campos=(Bem.nome,Bem.serie,Bem.numero_ngi,Bem.plaqueta_original)
        resultados=db.session.scalars(select(Bem).where(Bem.encerrado.is_(False),
            or_(*(c.icontains(busca,autoescape=True) for c in campos))).order_by(Bem.nome,Bem.id).limit(20)).all()
    return dict(bem_escolhido=selecionado,buscar_bem=busca,bens_resultados=resultados)


def texto_campo(form,campo,rotulo,limite,erros,minimo=0):
    valor=form.get(campo,'').strip()
    if len(valor)<minimo or len(valor)>limite:
        erros.append(f'{rotulo}: informe entre {minimo} e {limite} caracteres.')
    return valor


@app.route('/movimentacoes', methods=['GET', 'POST'])
@login_obrigatorio
def movimentacoes():
    formulario = request.method == 'POST' or request.args.get('aba') == 'cadastro'
    if formulario and g.usuario.leitura:
        abort(403)
    erros = []
    valores = request.form if request.method == 'POST' else request.args
    if request.method == 'POST':
        repetida = validar_token_operacao()
        if repetida is not None:
            return repetida
        try:
            chave = inteiro(request.form.get('bem_id'))
            if not chave:
                raise ValueError('Selecione o bem na pesquisa.')
            bem = trava_bem(chave)
            origem = request.form.get('base_origem', '')
            esperado = str(bem.base_id) if bem.base_id else 'sem_base'
            if origem != esperado:
                raise ValueError(
                    'O bem não pertence ao local de origem selecionado. Reabra a pesquisa para conferir o vínculo atual.'
                )
            if request.form.get('revisao_bem') != str(bem.revisao):
                raise ValueError(
                    'O bem foi atualizado. Reabra esta movimentação para conferir os dados atuais.'
                )
            if movimento_pendente(bem.id):
                raise ValueError('Já existe uma movimentação pendente para este bem.')
            if processo_aberto(bem.id):
                raise ValueError(
                    'O bem está em análise de baixa. Finalize ou cancele esse processo primeiro.'
                )
            temporaria = entrega_aberta(bem.id)
            retorno_id = inteiro(request.form.get('retorno_de'))
            tipo = request.form.get('tipo', '')
            if retorno_id:
                original = carregar(Movimento, retorno_id, True)
                if not temporaria or original.id != temporaria.id:
                    raise ValueError('Esta entrega não está aberta para devolução.')
                tipo = 'Devolução'
            elif temporaria:
                raise ValueError(
                    'Há uma entrega temporária aberta. Registre a devolução pela ficha da movimentação.'
                )
            elif tipo not in TIPOS_MOVIMENTO:
                raise ValueError('Selecione um tipo válido de movimentação.')
            base = db.session.get(BaseLocal, inteiro(request.form.get('base_id')))
            if not base or not base.ativo:
                raise ValueError('Selecione uma base de destino ativa.')
            responsavel = texto_campo(
                request.form, 'responsavel', 'Responsável no destino', 160, erros, 2
            )
            contato = texto_campo(request.form, 'contato', 'Contato', 160, erros)
            complemento = texto_campo(request.form, 'complemento', 'Sala / complemento', 200, erros)
            motivo = texto_campo(request.form, 'motivo', 'Justificativa', 3000, erros, 10)
            referencia = texto_campo(
                request.form, 'referencia', 'Processo / autorização', 200, erros
            )
            previsao = None
            if tipo in ('Entrega temporária', 'Manutenção'):
                try:
                    previsao = date.fromisoformat(request.form.get('previsao_retorno', ''))
                    if previsao < hoje_local():
                        raise ValueError()
                except ValueError:
                    erros.append('Informe uma previsão de retorno igual ou posterior a hoje.')
            if (
                tipo in ('Remanejamento interno', 'Transferência de responsável')
                and base.id == bem.base_id
                and responsavel == bem.responsavel
                and complemento == bem.complemento
            ):
                erros.append(
                    'O destino é igual ao atual. Informe o novo local, sala ou responsável.'
                )
            if erros:
                raise ValueError('Confira os campos destacados abaixo.')
            destino = dict(
                base_id=base.id,
                local=base.nome,
                endereco=base.endereco,
                latitude=str(base.latitude),
                longitude=str(base.longitude),
                responsavel=responsavel,
                responsavel_contato=contato,
                complemento=complemento,
            )
            mov = Movimento(
                bem_id=bem.id,
                tipo=tipo,
                origem=snapshot(bem),
                destino=destino,
                revisao_bem=bem.revisao,
                motivo=motivo,
                referencia=referencia,
                previsao_retorno=previsao,
                retorno_de=retorno_id,
                criado_por=g.usuario.id,
                criado_nome=g.usuario.nome,
            )
            db.session.add(mov)
            db.session.flush()
            flash(
                'Movimentação registrada. Confira a ficha e confirme a entrega para atualizar o bem.'
            )
            return finalizar_operacao(url_for('movimento_detalhe', movimento_id=mov.id))
        except ValueError as e:
            db.session.rollback()
            erros.append(str(e))
    if formulario:
        picker = busca_bem_selecionado()
        escolhido = picker['bem_escolhido']
        origem_selecionada = valores.get('base_origem', '') or (
            str(escolhido.base_id)
            if escolhido and escolhido.base_id
            else 'sem_base' if escolhido else ''
        )
        # Sem listas enormes de bens: apenas os cadastros dos locais são carregados aqui.
        bases_origem = db.session.scalars(select(BaseLocal).order_by(BaseLocal.nome)).all()
        tem_bens_sem_base = (
            db.session.scalar(
                select(Bem.id).where(Bem.base_id.is_(None), Bem.encerrado.is_(False)).limit(1)
            )
            is not None
        )
        retorno = (
            db.session.get(Movimento, inteiro(valores.get('retorno_de')))
            if inteiro(valores.get('retorno_de'))
            else None
        )
        return tela_operacao(
            'movimentacoes',
            'mov_form',
            'Movimentações',
            status=422 if erros else 200,
            valores=valores,
            erros=erros,
            operacao_token=token_operacao(),
            bases_destino=opcoes_bases(),
            tipos_movimento=TIPOS_MOVIMENTO,
            retorno=retorno,
            origem_selecionada=origem_selecionada,
            bases_origem=bases_origem,
            tem_bens_sem_base=tem_bens_sem_base,
            **picker
        )
    busca = request.args.get('q', '').strip()[:120]
    filtro = request.args.get('status', '')
    consulta = select(Movimento).join(Bem)
    if busca:
        consulta = consulta.where(
            or_(
                Bem.nome.icontains(busca, autoescape=True),
                Bem.serie.icontains(busca, autoescape=True),
                Bem.numero_ngi.icontains(busca, autoescape=True),
            )
        )
    if filtro == 'atrasados':
        consulta = consulta.where(
            Movimento.status == 'Concluída',
            Movimento.tipo.in_(('Entrega temporária', 'Manutenção')),
            Movimento.devolvido_em.is_(None),
            Movimento.previsao_retorno < hoje_local(),
        )
    elif filtro in ('Pendente', 'Concluída', 'Cancelada'):
        consulta = consulta.where(Movimento.status == filtro)
    return tela_operacao(
        'movimentacoes',
        'mov_lista',
        'Movimentações',
        q=busca,
        filtro=filtro,
        **paginar_operacao(consulta.order_by(Movimento.id.desc()))
    )


@app.get('/movimentacoes/<int:movimento_id>')
@login_obrigatorio
def movimento_detalhe(movimento_id):
    mov=carregar(Movimento,movimento_id)
    doc=db.session.scalar(select(Documento).where(Documento.movimento_id==mov.id))
    return tela_operacao('movimentacoes','mov_detalhe','Movimentação',mov=mov,
        ativo=carregar(Bem,mov.bem_id),documento=doc,hoje=hoje_local())


@app.post('/movimentacoes/<int:movimento_id>/confirmar')
@login_obrigatorio
def confirmar_movimento(movimento_id):
    # Mesmo encadeamento de locks das demais operações: bem, depois processo.
    original = carregar(Movimento, movimento_id)
    bem = carregar(Bem, original.bem_id, True)
    mov = carregar(Movimento, movimento_id, True)
    if mov.status != 'Pendente':
        flash('Esta movimentação já foi tratada. Nenhuma alteração foi repetida.')
        return redirect(url_for('movimento_detalhe', movimento_id=mov.id))
    erro = None
    if bem.encerrado or processo_aberto(bem.id):
        erro = 'O bem está baixado ou em análise de baixa.'
    elif request.form.get('confirmar') != 'sim':
        erro = 'Confirme que a entrega física foi realizada.'
    elif bem.revisao != mov.revisao_bem:
        erro = 'O cadastro mudou após a solicitação. Cancele e refaça a movimentação com os dados atuais.'
    base = db.session.get(BaseLocal, mov.destino['base_id'])
    if not base or not base.ativo:
        erro = 'O destino ficou inativo. Cancele e refaça a movimentação.'
    if erro:
        db.session.rollback()
        flash(erro)
        return redirect(url_for('movimento_detalhe', movimento_id=mov.id))
    antes = snapshot(bem)
    bem.base_id = base.id
    bem.local = base.nome
    bem.endereco = base.endereco
    bem.latitude = base.latitude
    bem.longitude = base.longitude
    bem.complemento = mov.destino['complemento']
    bem.responsavel = mov.destino['responsavel']
    bem.responsavel_contato = mov.destino['responsavel_contato']
    if mov.tipo == 'Manutenção':
        bem.situacao = 'Manutenção'
    elif mov.tipo == 'Devolução':
        entrega = carregar(Movimento, mov.retorno_de, True)
        if entrega.devolvido_em or entrega.status != 'Concluída':
            db.session.rollback()
            flash('A entrega original já foi encerrada.')
            return redirect(url_for('movimento_detalhe', movimento_id=mov.id))
        entrega.devolvido_em = datetime.now(timezone.utc)
        bem.situacao = entrega.origem.get('situacao', 'Em uso')
    bem.revisao += 1
    bem.atualizado_em = datetime.now(timezone.utc)
    bem.conferido = False
    mov.status = 'Concluída'
    mov.concluido_em = datetime.now(timezone.utc)
    mov.concluido_por = g.usuario.id
    registrar_evento(bem, 'Movimentação confirmada', antes)
    criar_documento(
        'Termo de movimentação',
        bem,
        dict(
            tipo=mov.tipo,
            origem=mov.origem,
            destino=snapshot(bem),
            justificativa=mov.motivo,
            referencia=mov.referencia,
            previsao_retorno=str(mov.previsao_retorno or ''),
            numero_movimento=mov.id,
        ),
        f'MOV-{mov.id:06d} · {bem.nome}',
        movimento=mov,
    )
    db.session.commit()
    flash('Movimentação confirmada. Local e responsável atualizados; termo disponível.')
    return redirect(url_for('movimento_detalhe', movimento_id=mov.id))


@app.post('/movimentacoes/<int:movimento_id>/cancelar')
@login_obrigatorio
def cancelar_movimento(movimento_id):
    obj = carregar(Movimento, movimento_id)
    carregar(Bem, obj.bem_id, True)
    mov = carregar(Movimento, movimento_id, True)
    motivo = request.form.get('motivo', '').strip()
    if mov.status == 'Pendente' and 10 <= len(motivo) <= 2000:
        mov.status = 'Cancelada'
        mov.motivo_cancelamento = motivo
        mov.concluido_em = datetime.now(timezone.utc)
        mov.concluido_por = g.usuario.id
        db.session.commit()
        flash('Movimentação cancelada. A localização do bem foi preservada.')
    else:
        db.session.rollback()
        flash(
            'Somente solicitações pendentes podem ser canceladas. Informe um motivo de 10 a 2.000 caracteres.'
        )
    return redirect(url_for('movimento_detalhe', movimento_id=mov.id))


@app.route('/documentos', methods=['GET', 'POST'])
@login_obrigatorio
def documentos():
    formulario = request.method == 'POST' or request.args.get('aba') == 'cadastro'
    if formulario and g.usuario.leitura:
        abort(403)
    erros = []
    if request.method == 'POST':
        repetida = validar_token_operacao()
        if repetida is not None:
            return repetida
        try:
            chave = inteiro(request.form.get('bem_id'))
            if not chave:
                raise ValueError('Selecione o bem na pesquisa.')
            bem = carregar(Bem, chave, True)
            tipo = request.form.get('tipo', '')
            if tipo not in ('Termo de responsabilidade', 'Relatório de ocorrência'):
                raise ValueError('Selecione um tipo válido.')
            if bem.encerrado and tipo == 'Termo de responsabilidade':
                raise ValueError('Não é possível emitir responsabilidade para um bem baixado.')
            justificativa = texto_campo(
                request.form, 'justificativa', 'Descrição / finalidade', 5000, erros, 10
            )
            referencia = texto_campo(
                request.form, 'referencia', 'Processo / referência', 200, erros
            )
            if erros:
                raise ValueError('Confira o preenchimento.')
            doc = criar_documento(
                tipo, bem, dict(justificativa=justificativa, referencia=referencia), bem.nome
            )
            return finalizar_operacao(url_for('documento_detalhe', documento_id=doc.id))
        except ValueError as e:
            db.session.rollback()
            erros.append(str(e))
    if formulario:
        return tela_operacao(
            'documentos',
            'doc_form',
            'Termos e documentos',
            status=422 if erros else 200,
            valores=request.form if request.method == 'POST' else request.args,
            erros=erros,
            operacao_token=token_operacao(),
            **busca_bem_selecionado()
        )
    busca = request.args.get('q', '').strip()[:120]
    consulta = select(Documento)
    if busca:
        consulta = consulta.where(
            or_(
                Documento.resumo.icontains(busca, autoescape=True),
                Documento.tipo.icontains(busca, autoescape=True),
            )
        )
    pagina = paginar_operacao(consulta.order_by(Documento.id.desc()))
    situacao_aceite = {}
    ids = [d.id for d in pagina['rows']]
    if ids:
        for aceite in db.session.scalars(select(AceiteTermo).where(AceiteTermo.documento_id.in_(ids)).order_by(AceiteTermo.id)):
            situacao_aceite[aceite.documento_id] = aceite.situacao
    return tela_operacao(
        'documentos',
        'doc_lista',
        'Termos e documentos',
        q=busca,
        situacao_aceite=situacao_aceite,
        **pagina
    )


def ids_bens_documento(doc):
    """Bens cobertos pelo documento: o bem principal e, no termo com vários bens, todos os do kit."""
    ids = [doc.bem_id] if doc.bem_id else []
    for bem_id in db.session.scalars(select(TermoBem.bem_id).where(TermoBem.documento_id == doc.id).order_by(TermoBem.bem_id)):
        if bem_id not in ids:
            ids.append(bem_id)
    return ids


def documentos_do_bem(bem_ids):
    """Consulta de documentos ligados aos bens, diretamente ou por termo com vários bens."""
    return or_(Documento.bem_id.in_(bem_ids),
               Documento.id.in_(select(TermoBem.documento_id).where(TermoBem.bem_id.in_(bem_ids))))


LIMITE_BENS_TERMO = 50


@app.route('/documentos/termo-varios-bens', methods=['GET', 'POST'])
@login_obrigatorio
def termo_kit():
    if g.usuario.leitura:
        abort(403)
    erros = []
    responsavel = (request.values.get('responsavel') or '').strip()[:160]
    selecionados = set()
    if request.method == 'POST':
        repetida = validar_token_operacao()
        if repetida is not None:
            return repetida
        try:
            ids = sorted({inteiro(x) for x in request.form.getlist('bem_id') if inteiro(x)})
            selecionados = set(ids)
            if not responsavel:
                raise ValueError('Selecione o responsável.')
            if not ids:
                raise ValueError('Marque pelo menos um bem para incluir no termo.')
            if len(ids) > LIMITE_BENS_TERMO:
                raise ValueError(f'Um termo pode ter até {LIMITE_BENS_TERMO} bens.')
            bens = [trava_bem(i) for i in ids]
            outros = [b.nome for b in bens if (b.responsavel or '').strip() != responsavel]
            if outros:
                raise ValueError('Estes bens não estão mais com ' + responsavel + ': ' + ', '.join(outros[:5]) + '. Atualize a página.')
            justificativa = texto_campo(request.form, 'justificativa', 'Descrição / finalidade', 5000, erros, 10)
            referencia = texto_campo(request.form, 'referencia', 'Processo / referência', 200, erros)
            if erros:
                raise ValueError('Confira o preenchimento.')
            if len(bens) == 1:
                doc = criar_documento('Termo de responsabilidade', bens[0],
                                      dict(justificativa=justificativa, referencia=referencia), bens[0].nome)
            else:
                nomes = ', '.join(b.nome for b in bens)
                resumo = (f'{len(bens)} bens · {responsavel}: {nomes}')[:300]
                doc = criar_documento('Termo de responsabilidade', bens[0],
                                      dict(justificativa=justificativa, referencia=referencia, responsavel=responsavel,
                                           bens=[snapshot(b) for b in bens]), resumo)
                for b in bens:
                    db.session.add(TermoBem(documento_id=doc.id, bem_id=b.id))
            return finalizar_operacao(url_for('documento_detalhe', documento_id=doc.id))
        except ValueError as e:
            db.session.rollback()
            erros.insert(0, str(e))
    responsaveis = db.session.execute(
        select(Bem.responsavel, func.count()).where(Bem.encerrado.is_(False), Bem.responsavel != '')
        .group_by(Bem.responsavel).order_by(Bem.responsavel)).all()
    bens_kit = db.session.scalars(select(Bem).where(Bem.encerrado.is_(False), Bem.responsavel == responsavel)
                                  .order_by(Bem.nome, Bem.id)).all() if responsavel else []
    return tela_operacao('documentos', 'doc_kit_form', 'Termo com vários bens', status=422 if erros else 200,
                         erros=erros, responsavel=responsavel, responsaveis=responsaveis, bens_kit=bens_kit,
                         selecionados=selecionados, valores=request.form if request.method == 'POST' else {},
                         operacao_token=token_operacao())


@app.get('/documentos/<int:documento_id>')
@login_obrigatorio
def documento_detalhe(documento_id):
    doc=carregar(Documento,documento_id)
    anexos=db.session.execute(select(AnexoDocumento.id,AnexoDocumento.nome,AnexoDocumento.criado_em).where(AnexoDocumento.documento_id==doc.id).order_by(AnexoDocumento.id)).all()
    aceites=db.session.scalars(select(AceiteTermo).where(AceiteTermo.documento_id==doc.id).order_by(AceiteTermo.id.desc())).all()
    aceite_ok=next((a for a in aceites if a.status=='Aceito'),None)
    pendente=next((a for a in aceites if a.situacao=='Pendente'),None)
    ctx=contexto_termo(doc,aceite_ok)
    ctx.pop('aceite_declaracao')
    return tela_operacao('documentos','doc_detalhe','Documento',anexos=anexos,
        aceites=aceites,aceite_pendente=pendente,
        pode_assinar=pode_assinar_documento(doc),declaracao_emitente=texto_declaracao_emitente(doc),
        **ctx,
        aceite_email_sugerido=email_sugerido_aceite(doc),aceite_nome_sugerido=nome_sugerido_aceite(doc),
        aceite_declaracao=texto_declaracao_aceite(doc))


# ---------- Assinatura eletrônica do emitente e verificação pública ----------
def integridade_documento(doc):
    """Recalcula o SHA-256 do conteúdo do documento (mesma regra da emissão)."""
    return hashlib.sha256(json.dumps(doc.dados, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def codigo_verificacao_documento(doc):
    return (doc.integridade or '')[:16]


def url_verificacao_documento(doc):
    return PUBLIC_URL + url_for('verificar_documento', documento_id=doc.id, codigo=codigo_verificacao_documento(doc))


def texto_declaracao_emitente(doc):
    if doc.tipo in TIPOS_ACEITE:
        return ('Atesto que os bens deste termo foram entregues ao responsável indicado e que as '
                'informações registradas neste documento estão corretas.')
    return 'Atesto que as informações registradas neste documento estão corretas.'


def pode_assinar_documento(doc):
    usuario = getattr(g, 'usuario', None)
    if not usuario or usuario.leitura:
        return False
    return usuario.id == doc.autor_id or usuario.perfil == 'Administrador'


@app.post('/documentos/<int:documento_id>/assinar')
@login_obrigatorio
def assinar_documento(documento_id):
    doc = carregar(Documento, documento_id, True)
    destino = url_for('documento_detalhe', documento_id=doc.id)
    if not pode_assinar_documento(doc):
        abort(403)
    if db.session.scalar(select(AssinaturaDocumento.id).where(AssinaturaDocumento.documento_id == doc.id)):
        db.session.rollback()
        flash('Este documento já foi assinado pelo emitente.')
        return redirect(destino)
    if request.form.get('atesto') != 'sim':
        db.session.rollback()
        flash('Marque a declaração para assinar o documento.')
        return redirect(destino)
    email = g.usuario.email
    if not limitar_recuperacao(email, finalidade='assinatura'):
        flash('Muitas tentativas a partir desta conexão. Aguarde 15 minutos e tente novamente.')
        return redirect(destino)
    doc = carregar(Documento, documento_id, True)
    usuario = db.session.get(Usuario, g.usuario.id)
    if not usuario or not usuario.ativo or not check_password_hash(usuario.senha_hash, request.form.get('senha', '')[:512]):
        db.session.rollback()
        flash('Senha incorreta. A assinatura não foi registrada.')
        return redirect(destino)
    if not hmac.compare_digest(integridade_documento(doc), doc.integridade):
        db.session.rollback()
        flash('O conteúdo deste documento não confere com o registro da emissão. A assinatura não foi registrada.')
        return redirect(destino)
    agora = datetime.now(timezone.utc)
    ip = (request.remote_addr or '')[:64]
    declaracao = texto_declaracao_emitente(doc)
    comprovante = hashlib.sha256(json.dumps(dict(
        documento=doc.id, integridade=doc.integridade, usuario=usuario.id, nome=usuario.nome,
        perfil=usuario.perfil, declaracao=declaracao, assinado_em=agora.isoformat(), ip=ip),
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    db.session.add(AssinaturaDocumento(
        documento_id=doc.id, usuario_id=usuario.id, nome=usuario.nome[:120], perfil=usuario.perfil[:30],
        declaracao=declaracao, integridade_documento=doc.integridade, ip=ip,
        user_agent=(request.headers.get('User-Agent') or '')[:300], assinado_em=agora, comprovante=comprovante))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash('Este documento já foi assinado pelo emitente.')
        return redirect(destino)
    flash('Documento assinado eletronicamente. A assinatura já aparece no documento impresso.')
    return redirect(destino)


VERIFICAR_TEMPLATE = r"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>Verificação de documento · Patrimônio Carajás</title>
<style>body{margin:0;font-family:Geist,system-ui,sans-serif;background:#f2f5f1;color:#17261d}.cx{max-width:560px;margin:32px auto;padding:0 16px}.card{background:#fff;border-radius:16px;box-shadow:0 8px 30px rgba(0,40,20,.10);overflow:hidden}.faixa{height:8px;background:linear-gradient(90deg,#004622 0 72%,#37784d 72% 90%,#a0c517 90%)}.top{display:flex;align-items:center;gap:12px;padding:20px 22px 0}.top img{height:46px}.top strong{display:block;font-size:15px;color:#004622}.top span{font-size:12px;color:#5d6f63}.st{margin:18px 22px;padding:14px 16px;border-radius:12px;font-weight:600;font-size:15px}.ok{background:#e5f3e9;color:#1d6b33;border:1px solid #bfe0c9}.bad{background:#fdecea;color:#8a2c1f;border:1px solid #f3c7c0}dl{margin:0 22px 18px;display:grid;grid-template-columns:auto 1fr;gap:9px 14px;font-size:13.5px}dt{color:#5d6f63}dd{margin:0;font-weight:500;overflow-wrap:anywhere}.h{font-family:ui-monospace,monospace;font-size:11.5px}p.n{margin:0 22px 22px;font-size:12px;color:#5d6f63;line-height:1.5}</style></head>
<body><div class="cx"><div class="card"><div class="faixa"></div><div class="top"><img src="{{ url_for('identidade_visual',nome='icmbio') }}" alt="ICMBio"><div><strong>Patrimônio Carajás</strong><span>NGI ICMBio Carajás · verificação de documento</span></div></div>
{% if doc %}<div class="st {{ 'ok' if integro else 'bad' }}">{{ '✓ Documento autêntico: o conteúdo confere com o registro do sistema.' if integro else 'Atenção: o conteúdo registrado não confere com o código de integridade.' }}</div>
<dl><dt>Documento</dt><dd>DOC-{{ '%06d'|format(doc.id) }} · {{ doc.tipo }}</dd><dt>Emitido em</dt><dd>{{ doc.criado_em|datahora }}</dd><dt>Emitente</dt><dd>{{ doc.autor_nome }}</dd>
<dt>Assinatura do emitente</dt><dd>{% if assinatura %}Assinado eletronicamente por {{ assinatura.nome }} em {{ assinatura.assinado_em|datahora }}{% else %}Não assinado eletronicamente{% endif %}</dd>
{% if aceita_eletronico %}<dt>Aceite do responsável</dt><dd>{% if aceite_ok %}Aceito eletronicamente por {{ aceite_ok.nome_digitado }} em {{ aceite_ok.respondido_em|datahora }}{% else %}Sem aceite eletrônico registrado{% endif %}</dd>{% endif %}
<dt>Integridade</dt><dd class="h">{{ doc.integridade }}</dd></dl>
<p class="n">Esta página confirma apenas a existência e a integridade do documento. Os bens e demais dados ficam disponíveis somente para usuários do sistema.</p>
{% else %}<div class="st bad">Documento não encontrado. Confira se o QR Code ou o endereço foi lido por completo.</div><p class="n">Se o problema continuar, procure o setor de Patrimônio do NGI ICMBio Carajás.</p>{% endif %}
</div></div></body></html>"""


@app.get('/verificar/<int:documento_id>/<codigo>')
def verificar_documento(documento_id, codigo):
    doc = db.session.get(Documento, documento_id)
    codigo = (codigo or '')[:64]
    if not doc or not hmac.compare_digest(codigo_verificacao_documento(doc), codigo):
        resposta = make_response(render_template_string(VERIFICAR_TEMPLATE, doc=None), 404)
    else:
        assinatura = db.session.scalar(select(AssinaturaDocumento).where(AssinaturaDocumento.documento_id == doc.id))
        aceite_ok = db.session.scalar(select(AceiteTermo).where(AceiteTermo.documento_id == doc.id,
                                                                 AceiteTermo.status == 'Aceito').order_by(AceiteTermo.id.desc()))
        resposta = make_response(render_template_string(
            VERIFICAR_TEMPLATE, doc=doc, assinatura=assinatura, aceite_ok=aceite_ok,
            aceita_eletronico=doc.tipo in TIPOS_ACEITE,
            integro=hmac.compare_digest(integridade_documento(doc), doc.integridade)))
    resposta.headers['Cache-Control'] = 'no-store'
    resposta.headers['X-Robots-Tag'] = 'noindex'
    return resposta


# Modelo do termo (o mesmo na tela interna, no aceite pelo e-mail e na impressão)
OP_TEMPLATES['tdoc_artigo'] = r'''<style>
.tdoc{--g:#004622;--g2:#37784d;--lime:#a0c517;--soft:#eef5e7;--ink:#17261d;--mut:#5d6f63;--ln:#dfe7dc;max-width:900px;margin:0 auto 24px;padding:0!important;overflow:hidden;color:var(--ink);background:#fff}
.tdoc *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
.tdoc-faixa{height:10px;background:linear-gradient(90deg,var(--g) 0 72%,var(--g2) 72% 90%,var(--lime) 90%)}
.tdoc-top{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:24px 40px 18px}
.tdoc-logos{display:flex;align-items:center;gap:16px;min-width:0}.tdoc-logos img.a{height:54px;width:auto}.tdoc-logos img.b{height:38px;width:auto;max-width:300px;object-fit:contain}.tdoc-logos .sep{width:1px;height:42px;background:var(--ln)}
.tdoc-cod{text-align:right}.tdoc-cod strong{display:block;font-family:'Geist Mono',ui-monospace,monospace;font-size:16px;color:var(--g);letter-spacing:.5px}.tdoc-cod small{display:block;font-size:11px;color:var(--mut);margin-top:3px}
.tdoc-hero{margin:0 40px;padding:22px 26px;border-radius:14px;background:linear-gradient(120deg,var(--g),#0d5a33);color:#fff;display:flex;justify-content:space-between;align-items:flex-end;gap:16px;position:relative;overflow:hidden}
.tdoc-hero:after{content:"";position:absolute;right:-60px;top:-60px;width:220px;height:220px;border-radius:50%;border:28px solid rgba(160,197,23,.18)}
.tdoc-hero>div{position:relative;z-index:1}.tdoc-hero .k{font-size:10px;letter-spacing:2.4px;text-transform:uppercase;color:#cfe6a0;font-weight:600}
.tdoc .tdoc-hero h1{font-size:27px;font-weight:700;margin:6px 0 4px;letter-spacing:-.3px;color:#fff}.tdoc .tdoc-hero p{font-size:12.5px;color:#d7e6dc;margin:0}
.tdoc-selo{position:relative;z-index:1;flex:none;background:#fff;color:var(--g);border-radius:999px;padding:7px 13px;font-size:11.5px;font-weight:700;display:flex;gap:7px;align-items:center}
.tdoc-selo i{width:17px;height:17px;border-radius:50%;background:var(--g2);display:grid;place-items:center;color:#fff;font-style:normal;font-size:10px}
.tdoc-alerta{margin:14px 40px 0;padding:11px 14px;border-radius:10px;background:#fdecea;color:#8a2c1f;border:1px solid #f3c7c0;font-size:12.5px;font-weight:600}
.tdoc-corpo{padding:22px 40px 0}
.tdoc-grid{display:grid;grid-template-columns:1.3fr 1fr 1fr;gap:10px}
.tdoc-cx{border:1px solid var(--ln);border-radius:10px;padding:10px 13px;min-width:0}.tdoc-cx.dest{background:var(--soft);border-color:#d3e6bf}
.tdoc-cx label{display:block;font-size:9.5px;letter-spacing:1.3px;text-transform:uppercase;color:var(--mut);font-weight:600;margin-bottom:4px}
.tdoc-cx b{display:block;font-size:13.5px;font-weight:600;overflow-wrap:anywhere}.tdoc-cx small{display:block;font-size:11px;color:var(--mut);margin-top:2px;overflow-wrap:anywhere}
.tdoc .tdoc-h{font-size:13.5px;font-weight:700;color:var(--g);margin:22px 0 9px;display:flex;align-items:center;gap:8px}
.tdoc-h:before{content:"";width:4px;height:14px;border-radius:2px;background:var(--lime)}.tdoc-h em{font-style:normal;font-size:10.5px;background:var(--soft);color:var(--g2);padding:2px 8px;border-radius:999px}
.tdoc-tab{width:100%;border-collapse:separate;border-spacing:0;font-size:11.5px;border:1px solid var(--ln);border-radius:10px;overflow:hidden}
.tdoc-tab th{background:#f4f7f3;color:var(--mut);font-size:9px;letter-spacing:1px;text-transform:uppercase;text-align:left;padding:8px 9px;font-weight:600;border-bottom:1px solid var(--ln)}
.tdoc-tab td{padding:8px 9px;border-bottom:1px solid #edf1ec;vertical-align:middle;color:var(--ink)}.tdoc-tab tbody tr:last-child td{border-bottom:0}
.tdoc-tab td small{display:block;color:var(--mut);font-size:10px;margin-top:1px}.tdoc-tab td.n{color:var(--mut);width:22px}.tdoc-tab .r{text-align:right;white-space:nowrap}
.tdoc-tab .mono{font-family:'Geist Mono',ui-monospace,monospace;font-size:10.5px;overflow-wrap:anywhere}
.tdoc-plq{font-family:'Geist Mono',ui-monospace,monospace;font-size:9.5px;background:var(--g);color:#fff;padding:3px 6px;border-radius:5px;white-space:nowrap}.tdoc-plq.sem{background:#eef1ed;color:var(--mut)}
.tdoc-pill{font-size:9.5px;padding:2px 8px;border-radius:999px;font-weight:600;background:#e3f1e6;color:#1d6b33;white-space:nowrap}.tdoc-pill.warn{background:#fdf1dc;color:#8a5a00}.tdoc-pill.bad{background:#fdecea;color:#8a2c1f}
.tdoc-tab tfoot td{background:#f4f7f3;font-weight:600;border-top:1px solid var(--ln)}
.tdoc-duo{display:grid;grid-template-columns:1fr 1fr;gap:4px 24px}.tdoc-duo .full{grid-column:1/-1}
.tdoc .tdoc-txt{font-size:12px;line-height:1.55;color:#33453a;margin:0;white-space:pre-line}
.tdoc-decl{border-radius:10px;background:#fafcf8;border:1px solid var(--ln);border-left:4px solid var(--g2);padding:13px 16px}
.tdoc-ass{display:grid;grid-template-columns:1fr 1fr;gap:26px;margin-top:28px;break-inside:avoid}
.tdoc-linha{text-align:center;padding-top:44px}.tdoc-linha .lin{border-top:1px solid #9aa89f;margin:0 30px 7px}.tdoc-linha b{font-size:12.5px}.tdoc-linha small{display:block;font-size:10.5px;color:var(--mut);margin-top:2px}
.tdoc-stamp{border:1.5px solid var(--g2);border-radius:12px;padding:12px 14px;display:flex;gap:12px;align-items:center;background:linear-gradient(135deg,#f2f8ec,#fff);min-width:0}
.tdoc-stamp .ck{width:38px;height:38px;border-radius:50%;background:var(--g2);color:#fff;display:grid;place-items:center;font-size:19px;flex:none}
.tdoc-stamp .t{font-size:9.5px;letter-spacing:1.4px;font-weight:700;color:var(--g2)}.tdoc-stamp b{display:block;font-size:13.5px;margin:2px 0}.tdoc-stamp small{display:block;font-size:10.5px;color:var(--mut);line-height:1.45;overflow-wrap:anywhere}
.tdoc-rod{margin:26px 40px 0;padding:14px 0 24px;border-top:1px dashed #cdd8cb;display:flex;gap:16px;align-items:center;break-inside:avoid}
.tdoc-rod img{width:76px;height:76px;padding:4px;border:1px solid var(--ln);border-radius:8px;flex:none}
.tdoc-rod .v{min-width:0;flex:1}.tdoc-rod .v b{font-size:12px;color:var(--g)}.tdoc-rod .v p{font-size:9.5px;color:var(--mut);line-height:1.5;margin:3px 0 0;overflow-wrap:anywhere}
.tdoc-rod .v code{font-family:'Geist Mono',ui-monospace,monospace;font-size:8.6px;color:#6d7d72;word-break:break-all;background:none;padding:0}
.tdoc-rod .pg{text-align:right;font-size:9.5px;color:var(--mut);max-width:190px;flex:none}
.tdoc-assinar-form{display:grid;gap:14px;max-width:560px}.tdoc-assinar-form .atesto{display:flex;gap:10px;align-items:flex-start;font-size:13.5px;line-height:1.5;padding:12px 14px;border:1px solid #d3e6bf;background:#f4f9ef;border-radius:10px}.tdoc-assinar-form .atesto input{margin-top:4px;width:17px;height:17px;flex:none}
@media screen and (max-width:760px){.tdoc-tab thead{display:none}.tdoc-tab,.tdoc-tab tbody,.tdoc-tab tfoot{display:block}.tdoc-tab tr{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;padding:10px 12px;border-bottom:1px solid #edf1ec}.tdoc-tab td{display:block;padding:0;border:0!important;text-align:left!important}.tdoc-tab td.n{grid-row:span 6}.tdoc-tab td.bem{grid-column:2}.tdoc-tab td[data-rot]{grid-column:2;font-size:12px}.tdoc-tab td[data-rot]:before{content:attr(data-rot) ': ';color:#5d6f63;font-size:11px}.tdoc-tab tfoot tr{grid-template-columns:1fr auto}.tdoc-tab tfoot td{grid-row:auto!important}.tdoc-rod .pg{flex:1 1 100%}.tdoc-top,.tdoc-rod{flex-wrap:wrap}.tdoc-top{padding:18px 18px 14px}.tdoc-logos img.b{max-width:170px}.tdoc-hero{margin:0 18px;flex-direction:column;align-items:flex-start}.tdoc-corpo{padding:18px 18px 0}.tdoc-rod{margin:22px 18px 0}.tdoc-grid,.tdoc-duo,.tdoc-ass{grid-template-columns:1fr}.tdoc-cod{text-align:left}.tdoc-logos img.b{max-width:200px}.tdoc-tab{display:block;overflow-x:auto}.tdoc-rod .pg{text-align:left;max-width:none}}
@media print{.tdoc{max-width:none}.tdoc-top{padding:0 0 10px}.tdoc-logos img.a{height:46px}.tdoc-hero{margin:0;padding:16px 20px}.tdoc .tdoc-hero h1{font-size:22px}.tdoc-alerta{margin:10px 0 0}.tdoc-corpo{padding:14px 0 0}.tdoc .tdoc-h{margin:14px 0 7px}.tdoc-ass{margin-top:18px}.tdoc-linha{padding-top:30px}.tdoc-rod{margin:16px 0 0;padding:10px 0 0}.tdoc-rod img{width:64px;height:64px}.tdoc-tab tr{break-inside:avoid}}
</style>
<article class="panel op-document tdoc">{% set b=doc.dados.bem %}{% set resp=doc.dados.get('responsavel') or b.responsavel %}{% set ref=doc.dados.get('referencia') or doc.dados.get('processo') %}
<div class="tdoc-faixa"></div>
<header class="tdoc-top"><div class="tdoc-logos"><img class="a" src="{{ url_for('identidade_visual',nome='icmbio') }}" alt="ICMBio"><span class="sep"></span><img class="b" src="{{ url_for('identidade_visual',nome='unidades') }}" alt="Unidades de conservação do NGI ICMBio Carajás"></div><div class="tdoc-cod"><strong>DOC-{{ '%06d'|format(doc.id) }}</strong><small>Emitido em {{ doc.criado_em|datahora }}</small><small>Patrimônio Carajás · NGI ICMBio Carajás</small></div></header>
<div class="tdoc-hero"><div><span class="k">Documento patrimonial</span><h1>{{ doc.tipo }}</h1><p>{% if aceita_eletronico %}Guarda, conservação e uso de bens patrimoniais do NGI ICMBio Carajás{% else %}Registro do controle patrimonial do NGI ICMBio Carajás{% endif %}</p></div>{% if aceite_ok or assinatura %}<span class="tdoc-selo"><i>✓</i>{{ 'Assinado e aceito eletronicamente' if aceite_ok and assinatura else ('Aceito eletronicamente' if aceite_ok else 'Assinado eletronicamente') }}</span>{% endif %}</div>
{% if not integro %}<div class="tdoc-alerta">Atenção: o conteúdo deste documento não confere com o código de integridade registrado na emissão.</div>{% endif %}
<div class="tdoc-corpo">
<div class="tdoc-grid"><div class="tdoc-cx dest"><label>{{ 'Responsável pelos bens' if bens_doc|length > 1 else 'Responsável pelo bem' }}</label><b>{{ resp or 'Não informado' }}</b>{% if aceite_ok %}<small>{{ aceite_ok.email }}</small>{% elif b.get('responsavel_contato') %}<small>{{ b.responsavel_contato }}</small>{% endif %}</div>
<div class="tdoc-cx"><label>Convênio / projeto</label><b>{{ b.get('convenio') or 'Não informado' }}</b>{% if b.get('coordenacao') %}<small>Coordenação {{ b.coordenacao }}</small>{% endif %}</div>
<div class="tdoc-cx"><label>Processo / referência</label><b>{{ ref or 'Não informado' }}</b>{% if doc.dados.get('tipo') %}<small>{{ doc.dados.tipo }}</small>{% endif %}</div></div>
<h2 class="tdoc-h">{{ 'Bens sob responsabilidade' if aceita_eletronico else ('Bens do documento' if bens_doc|length > 1 else 'Bem do documento') }} <em>{{ bens_doc|length }} {{ 'itens' if bens_doc|length > 1 else 'item' }}</em></h2>
<table class="tdoc-tab"><thead><tr><th>#</th><th>Plaqueta</th><th>Bem · marca / modelo</th><th>Série</th><th>Local</th><th>Estado</th><th class="r">Valor</th></tr></thead><tbody>
{% for x in bens_doc %}{% set plq=x.get('numero_ngi') or x.get('plaqueta_original') %}<tr><td class="n">{{ loop.index }}</td><td data-rot="Plaqueta"><span class="tdoc-plq {{ '' if plq else 'sem' }}">{{ plq or 'Sem plaqueta' }}</span></td><td class="bem"><b>{{ x.get('nome') }}</b>{% if x.get('marca') or x.get('modelo') %}<small>{{ x.get('marca') or '' }}{{ ' · ' if x.get('marca') and x.get('modelo') }}{{ x.get('modelo') or '' }}</small>{% endif %}</td><td class="mono" data-rot="Série">{{ x.get('serie') or '—' }}</td><td data-rot="Local">{{ x.get('local') or '—' }}{% if x.get('complemento') %}<small>{{ x.complemento }}</small>{% endif %}</td><td data-rot="Estado">{% set c=x.get('conservacao') or '' %}{% if c %}<span class="tdoc-pill {{ 'warn' if c=='Regular' else ('bad' if c in ('Ruim','Inservível') else '') }}">{{ c }}</span>{% else %}—{% endif %}</td><td class="r" data-rot="Valor">{{ x._valor|brl if x._valor is not none else '—' }}</td></tr>{% endfor %}
</tbody>{% if total_bens_doc is not none and bens_doc|length > 1 %}<tfoot><tr><td colspan="6">Valor total dos bens</td><td class="r">{{ total_bens_doc|brl }}</td></tr></tfoot>{% endif %}</table>
<div class="tdoc-duo">{% for campo,label in [('justificativa','Descrição / justificativa'),('previsao_retorno','Previsão de retorno'),('motivo','Motivo'),('titularidade','Titular / proprietário'),('destinacao','Destinação'),('avaliacao','Avaliação / comissão'),('decisao','Decisão'),('autoridade','Autoridade competente'),('autorizacao','Autorização / decisão')] %}{% if doc.dados.get(campo) %}<div><h3 class="tdoc-h">{{ label }}</h3><p class="tdoc-txt">{{ doc.dados[campo] }}</p></div>{% endif %}{% endfor %}
{% if doc.dados.get('processo') and doc.dados.get('referencia') %}<div><h3 class="tdoc-h">Processo administrativo</h3><p class="tdoc-txt">{{ doc.dados.processo }}</p></div>{% endif %}
{% if doc.dados.get('origem') %}<div><h3 class="tdoc-h">Origem → destino</h3><p class="tdoc-txt">De: {{ doc.dados.origem.local }} · {{ doc.dados.origem.responsavel }}
Para: {{ doc.dados.destino.local }} · {{ doc.dados.destino.responsavel }}</p></div>{% endif %}</div>
{% if aceita_eletronico %}<h3 class="tdoc-h">Declaração do responsável</h3><div class="tdoc-decl"><p class="tdoc-txt">{{ aceite_declaracao }}</p></div>{% endif %}
<div class="tdoc-ass">
{% if assinatura %}<div class="tdoc-stamp"><div class="ck">✓</div><div><div class="t">EMITIDO E ASSINADO ELETRONICAMENTE</div><b>{{ assinatura.nome }}</b><small>Assinatura ASS-{{ '%06d'|format(assinatura.id) }} · {{ assinatura.assinado_em|datahora }}<br>Login e senha no Patrimônio Carajás · IP {{ assinatura.ip or 'não registrado' }}</small></div></div>
{% else %}<div class="tdoc-linha"><div class="lin"></div><b>{{ doc.autor_nome }}</b><small>Emitente · responsável pelo registro</small><small>Setor de Patrimônio · NGI ICMBio Carajás</small></div>{% endif %}
{% if aceite_ok %}<div class="tdoc-stamp"><div class="ck">✓</div><div><div class="t">ACEITO ELETRONICAMENTE</div><b>{{ aceite_ok.nome_digitado }}</b><small>Aceite ACE-{{ '%06d'|format(aceite_ok.id) }} · {{ aceite_ok.respondido_em|datahora }}<br>Link pessoal enviado a {{ aceite_ok.email }} · IP {{ aceite_ok.ip }}</small></div></div>
{% else %}<div class="tdoc-linha"><div class="lin"></div><b>{{ resp or 'Responsável' }}</b><small>Responsável / recebedor · assinatura</small></div>{% endif %}
</div></div>
<div class="tdoc-rod"><img src="{{ qr_verificacao }}" alt="QR Code para verificar este documento"><div class="v"><b>Verifique a autenticidade deste documento</b><p>Aponte a câmera para o QR Code ou abra o endereço: <code>{{ url_verificacao }}</code><br>Registro emitido por {{ doc.autor_nome }}. Integridade (SHA-256): <code>{{ doc.integridade }}</code>{% if assinatura %}<br>Assinatura do emitente ASS-{{ '%06d'|format(assinatura.id) }} · comprovante (SHA-256): <code>{{ assinatura.comprovante }}</code>{% endif %}{% if aceite_ok %}<br>Aceite eletrônico ACE-{{ '%06d'|format(aceite_ok.id) }}: termo aceito por {{ aceite_ok.nome_digitado }} ({{ aceite_ok.email }}) em {{ aceite_ok.respondido_em|datahora }}, pelo link pessoal enviado ao e-mail, IP {{ aceite_ok.ip }}. Comprovante (SHA-256): <code>{{ aceite_ok.comprovante }}</code>{% endif %}</p></div><div class="pg">Documento de apoio ao controle patrimonial. Não substitui o processo administrativo competente.</div></div>
</article>'''


def contexto_termo(doc, aceite_ok=None):
    """Tudo o que o modelo do termo precisa para ser desenhado."""
    assinatura = db.session.scalar(select(AssinaturaDocumento).where(AssinaturaDocumento.documento_id == doc.id))
    bens_doc = []
    for x in (doc.dados.get('bens') or [doc.dados.get('bem') or {}]):
        try:
            v = Decimal(x['valor']) if x.get('valor') not in (None, '') else None
        except (InvalidOperation, TypeError):
            v = None
        bens_doc.append(dict(x, _valor=v))
    valores = [x['_valor'] for x in bens_doc if x['_valor'] is not None]
    url_verif = url_verificacao_documento(doc)
    return dict(doc=doc, assinatura=assinatura, aceite_ok=aceite_ok,
                integro=hmac.compare_digest(integridade_documento(doc), doc.integridade),
                bens_doc=bens_doc, total_bens_doc=sum(valores) if valores else None,
                url_verificacao=url_verif, qr_verificacao=qr_data_url(url_verif),
                aceita_eletronico=doc.tipo in TIPOS_ACEITE, aceite_declaracao=texto_declaracao_aceite(doc))


def ler_arquivo_documento(arquivo):
    """Valida um PDF ou imagem (até 5 MB) e devolve (dados, mime, extensão)."""
    if not arquivo or not arquivo.filename:
        raise ValueError('Selecione um PDF ou imagem para anexar.')
    arquivo.stream.seek(0)
    bruto = arquivo.read(5 * 1024 * 1024 + 1)
    if not bruto:
        raise ValueError('O anexo chegou vazio. Selecione novamente o arquivo antes de enviar.')
    if len(bruto) > 5 * 1024 * 1024:
        raise ValueError('O anexo deve ter até 5 MB.')
    nome_original = arquivo.filename.casefold()
    # PDFs podem conter prefixos de scanner e bytes depois de %%EOF.
    # O parser valida a estrutura; nunca encaminhar um PDF para o leitor de fotos.
    parece_pdf = (
        b'%PDF-' in bruto[:1024]
        or nome_original.endswith('.pdf')
        or arquivo.mimetype == 'application/pdf'
    )
    if parece_pdf:
        if b'%PDF-' not in bruto[:1024] or b'%%EOF' not in bruto:
            raise ValueError(
                'Não foi possível abrir este PDF: o conteúdo está incompleto ou não corresponde a um PDF válido. Exporte novamente o documento.'
            )
        try:
            leitor = PdfReader(io.BytesIO(bruto), strict=False)
            protegido = leitor.is_encrypted
            numero_paginas = 0 if protegido else len(leitor.pages)
        except Exception:
            raise ValueError(
                'Não foi possível abrir este PDF. O arquivo pode estar incompleto ou inválido. Exporte novamente como PDF e tente anexar.'
            ) from None
        if not protegido and not numero_paginas:
            raise ValueError('O PDF não contém páginas. Escolha outro arquivo.')
        # Preserva os bytes originais, inclusive assinaturas digitais existentes.
        dados = bruto
        mime = 'application/pdf'
        ext = 'pdf'
    else:
        if nome_original.endswith(('.doc', '.docx', '.xls', '.xlsx', '.odt')):
            raise ValueError(
                'Este anexo é um arquivo de edição. Salve ou exporte como PDF antes de anexar.'
            )
        try:
            # Stream novo: a detecção do tipo não consome a imagem usada na conversão.
            imagem = FileStorage(
                stream=io.BytesIO(bruto),
                filename=arquivo.filename,
                content_type=arquivo.content_type,
            )
            dados = ler_foto(imagem)
        except ValueError:
            raise ValueError(
                'Não foi possível abrir a imagem do anexo. Envie JPEG, PNG, WebP, HEIC/HEIF ou AVIF válido, ou um documento em PDF (até 5 MB).'
            ) from None
        if not dados:
            raise ValueError('Selecione um PDF ou imagem válida para anexar.')
        mime = 'image/jpeg'
        ext = 'jpg'
    return dados, mime, ext


@app.post('/documentos/<int:documento_id>/anexos')
@login_obrigatorio
def anexar_documento(documento_id):
    doc = carregar(Documento, documento_id, True)
    try:
        if (
            db.session.scalar(
                select(func.count())
                .select_from(AnexoDocumento)
                .where(AnexoDocumento.documento_id == doc.id)
            )
            or 0
        ) >= 10:
            raise ValueError('Limite de dez anexos por documento.')
        arquivo = request.files.get('arquivo')
        dados, mime, ext = ler_arquivo_documento(arquivo)
        resumo = hashlib.sha256(dados).hexdigest()
        if db.session.scalar(
            select(AnexoDocumento.id).where(
                AnexoDocumento.documento_id == doc.id, AnexoDocumento.sha256 == resumo
            )
        ):
            raise ValueError('Este arquivo já está anexado ao documento.')
        nome = (
            re.sub(r'[^\w .()-]', '_', arquivo.filename.rsplit('/', 1)[-1].rsplit('\\', 1)[-1])[
                :140
            ].rsplit('.', 1)[0]
            or 'Anexo'
        )
        db.session.add(
            AnexoDocumento(
                documento_id=doc.id,
                nome=nome + '.' + ext,
                mime=mime,
                dados=dados,
                sha256=resumo,
                autor_id=g.usuario.id,
            )
        )
        db.session.commit()
        flash('Comprovante anexado ao documento.')
    except ValueError as e:
        db.session.rollback()
        flash(str(e))
    return redirect(url_for('documento_detalhe', documento_id=doc.id))


@app.get('/documentos/anexos/<int:anexo_id>')
@login_obrigatorio
def baixar_anexo(anexo_id):
    anexo=carregar(AnexoDocumento,anexo_id)
    return Response(anexo.dados,mimetype=anexo.mime,headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(anexo.nome)})


TIPOS_ACEITE = ('Termo de responsabilidade', 'Termo de movimentação')
VALIDADE_ACEITE = 7 * 86400
PADRAO_EMAIL = r'[^\s@]+@[^\s@]+\.[^\s@]+'


def nome_sugerido_aceite(doc):
    destino = doc.dados.get('destino') or {}
    return (doc.dados.get('responsavel') or destino.get('responsavel') or (doc.dados.get('bem') or {}).get('responsavel') or '')[:160]


def email_sugerido_aceite(doc):
    contato = ((doc.dados.get('bem') or {}).get('responsavel_contato') or '').strip()
    if doc.bem_id and not contato:
        bem = db.session.get(Bem, doc.bem_id)
        contato = (bem.responsavel_contato or '').strip() if bem else ''
    achado = re.search(PADRAO_EMAIL, contato)
    return achado.group(0).casefold()[:254] if achado else ''


def texto_declaracao_aceite(doc):
    if len(doc.dados.get('bens') or []) > 1:
        return ('Declaro que recebi os bens identificados neste termo e assumo a responsabilidade pela sua guarda, '
                'conservação e uso adequado, exclusivamente no interesse do serviço. Comprometo-me a comunicar ao '
                'Patrimônio qualquer dano, extravio, furto ou necessidade de movimentação, e a devolvê-los quando solicitado.')
    if doc.tipo == 'Termo de movimentação':
        return ('Declaro que recebi o bem identificado neste termo, no local e nas condições descritas, '
                'e assumo a responsabilidade pela sua guarda, conservação e uso adequado a partir desta data. '
                'Comprometo-me a comunicar ao Patrimônio qualquer dano, extravio, furto ou nova movimentação.')
    return ('Declaro que recebi o bem identificado neste termo e assumo a responsabilidade pela sua guarda, '
            'conservação e uso adequado, exclusivamente no interesse do serviço. Comprometo-me a comunicar ao '
            'Patrimônio qualquer dano, extravio, furto ou necessidade de movimentação, e a devolvê-lo quando solicitado.')


def numero_documento(doc):
    return 'DOC-%06d' % doc.id


@app.post('/documentos/<int:documento_id>/aceite')
@login_obrigatorio
def enviar_aceite(documento_id):
    doc = carregar(Documento, documento_id, True)
    destino = url_for('documento_detalhe', documento_id=doc.id)
    if doc.tipo not in TIPOS_ACEITE:
        abort(404)
    email = request.form.get('email', '').strip().casefold()[:254]
    nome = ' '.join(request.form.get('nome', '').split())[:160]
    if not re.fullmatch(PADRAO_EMAIL, email):
        flash('Informe um e-mail válido para enviar o termo.')
        return redirect(destino)
    if len(nome) < 3:
        flash('Informe o nome do responsável que vai dar o aceite.')
        return redirect(destino)
    try:
        configuracao_email()
    except ValueError:
        flash('O envio de e-mails ainda não está configurado no servidor. Procure o administrador.')
        return redirect(destino)
    aceites = db.session.scalars(select(AceiteTermo).where(AceiteTermo.documento_id == doc.id)
        .with_for_update().execution_options(populate_existing=True)).all()
    if any(a.status == 'Aceito' for a in aceites):
        flash('Este termo já foi aceito eletronicamente.')
        return redirect(destino)
    agora = datetime.now(timezone.utc)
    recente = [a for a in aceites if a.situacao == 'Pendente' and a.criado_em and
               (a.criado_em if a.criado_em.tzinfo else a.criado_em.replace(tzinfo=timezone.utc)) > agora - timedelta(seconds=60)]
    if recente:
        flash('Um link acabou de ser enviado. Aguarde um minuto antes de reenviar.')
        return redirect(destino)
    for a in aceites:
        if a.status == 'Pendente':
            a.status = 'Cancelado'
    codigo = secrets.token_urlsafe(32)
    aceite = AceiteTermo(documento_id=doc.id, email=email, nome_destinatario=nome,
        token_hash=digest('aceite:' + codigo), status='Pendente', integridade_documento=doc.integridade,
        enviado_por=g.usuario.id, enviado_por_nome=g.usuario.nome, criado_em=agora,
        expira_em=int(time.time()) + VALIDADE_ACEITE)
    db.session.add(aceite)
    for bem_id in ids_bens_documento(doc):
        bem = db.session.get(Bem, bem_id)
        if bem:
            registrar_evento(bem, 'Termo enviado para aceite eletrônico')
    db.session.commit()
    aceite_id = aceite.id
    link = PUBLIC_URL + url_for('aceite_termo', codigo=codigo)
    b = doc.dados.get('bem') or {}
    identificacao = ' · '.join(x for x in (b.get('nome'), b.get('numero_ngi') or b.get('plaqueta_original')) if x)
    lista_bens = doc.dados.get('bens') or []
    if len(lista_bens) > 1:
        nomes = [x.get('nome') or '' for x in lista_bens]
        identificacao = f'{len(nomes)} bens: ' + ', '.join(nomes[:6]) + (f' e mais {len(nomes) - 6}' if len(nomes) > 6 else '')
    corpo = (f'Olá, {nome}.\n\nO Patrimônio Carajás (NGI ICMBio Carajás) enviou para o seu aceite o '
        f'{doc.tipo.lower()} {numero_documento(doc)}, referente a: {identificacao}.\n\n'
        f'Para ler o termo e registrar o seu aceite, acesse:\n{link}\n\n'
        'Não é preciso login nem senha. O link é pessoal, vale por 7 dias e funciona uma única vez. '
        'Se você não reconhece este termo, use a opção "Não concordo" na mesma página.\n\nNGI ICMBio Carajás')
    corpo_html = ('<!doctype html><html lang="pt-BR"><body style="font-family:Arial,sans-serif;background:#F4F5F1;padding:24px;color:#0E3B2B">'
        '<div style="max-width:560px;margin:auto;background:white;padding:32px;border-radius:16px;border-top:6px solid #0B3325">'
        '<h2>Patrimônio Carajás</h2><p>Olá, ' + html_escape(nome) + '.</p>'
        '<p>O NGI ICMBio Carajás enviou para o seu aceite o <strong>' + html_escape(doc.tipo.lower()) + ' ' + numero_documento(doc) + '</strong>, referente a:</p>'
        '<p style="background:#F0F5F1;padding:14px 16px;border-radius:8px">' + html_escape(identificacao) + '</p>'
        '<p><a style="display:inline-block;background:#0E3B2B;color:white;padding:15px 22px;border-radius:8px;text-decoration:none" href="' + html_escape(link, quote=True) + '">Ler e aceitar o termo</a></p>'
        '<p>Não é preciso login nem senha. O link é pessoal, vale por <strong>7 dias</strong> e funciona uma única vez.</p>'
        '<p>Se você não reconhece este termo, abra o link e use a opção “Não concordo”.</p><hr><small>NGI ICMBio Carajás</small></div></body></html>')
    try:
        enviar_email_sistema(email, f'Termo para aceite · {numero_documento(doc)} · Patrimônio Carajás', corpo, corpo_html)
    except (OSError, smtplib.SMTPException, ValueError):
        db.session.execute(AceiteTermo.__table__.update().where(AceiteTermo.id == aceite_id).values(status='Cancelado'))
        db.session.commit()
        app.logger.warning('Envio do termo para aceite não confirmado. Confira SMTP no Render e execute testar-email.')
        flash('Não foi possível enviar o e-mail agora. O link foi cancelado; tente novamente em alguns minutos.')
        return redirect(destino)
    flash(f'Termo enviado para {email}. Assim que a pessoa aceitar, o registro aparece aqui.')
    return redirect(destino)


@app.post('/documentos/<int:documento_id>/aceite/cancelar')
@login_obrigatorio
def cancelar_aceite(documento_id):
    doc = carregar(Documento, documento_id, True)
    alterados = 0
    for a in db.session.scalars(select(AceiteTermo).where(AceiteTermo.documento_id == doc.id,
            AceiteTermo.status == 'Pendente').with_for_update()):
        a.status = 'Cancelado'
        alterados += 1
    db.session.commit()
    flash('Link de aceite cancelado.' if alterados else 'Não há link pendente para cancelar.')
    return redirect(url_for('documento_detalhe', documento_id=doc.id))


ACEITE_TEMPLATE = r"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Aceite de termo · Patrimônio Carajás</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box}body{margin:0;background:#F4F5F1;color:#173f30;font:15px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
.top{background:#0B3325;color:#fff;padding:18px 20px}.top div div{display:block!important}.top div{max-width:900px;margin:auto;display:flex;align-items:center;gap:14px}
.top img{height:42px;width:auto;background:#fff;border-radius:9px;padding:4px 7px}.top strong{display:block;font-size:16px}.top span{font-size:12px;opacity:.8}
main{max-width:900px;margin:24px auto 48px;padding:0 16px}.saudacao{margin:4px 2px 18px}.saudacao h1{font-size:24px;margin:4px 0 4px;color:#004622}.saudacao p{margin:0;color:#4f6658}
.tdoc{border:1px solid #dfe7e1;border-radius:14px;box-shadow:0 8px 28px rgba(0,50,20,.08);margin-bottom:18px!important}.card{background:#fff;border:1px solid #dfe7e1;border-radius:14px;padding:28px;margin-bottom:18px}
.doc-head{text-align:center;border-bottom:2px solid #174c37;padding-bottom:18px;margin-bottom:20px}.doc-head h1{font-size:21px;margin:6px 0}.doc-head small{color:#6e8074}
.eyebrow{font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:#5b7a66}
h2{font-size:16px;margin:22px 0 10px}dl{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px 20px;margin:0}
dt{font-size:11px;color:#738679}dd{margin:2px 0 0;font-size:14px;overflow-wrap:anywhere}p.texto{white-space:pre-wrap;overflow-wrap:anywhere;margin:0}
.declaracao{background:#F0F5F1;border-left:4px solid #15573F;padding:16px 18px;border-radius:8px;margin-top:22px}
.check{display:flex;gap:12px;align-items:flex-start;margin:18px 0}.check input{width:22px;height:22px;flex-shrink:0;margin-top:2px;accent-color:#15573F}
label{font-size:13px;font-weight:600}input[type=text],textarea{width:100%;font:16px system-ui,sans-serif;padding:13px 14px;border:1px solid #bfd0c4;border-radius:9px;margin:6px 0 4px;color:#173f30}
textarea{min-height:96px;resize:vertical}small.dica{display:block;color:#6d8174;font-size:12px}
.btn{display:block;width:100%;border:0;border-radius:10px;padding:16px;font:700 16px system-ui,sans-serif;cursor:pointer;margin-top:16px;background:#0E3B2B;color:#fff}
.btn.sec{background:#fff;color:#8a2c1f;border:1px solid #e3b9b1}details{margin-top:20px;border-top:1px solid #e3eae5;padding-top:16px}summary{cursor:pointer;color:#8a2c1f;font-weight:600}
.erro{background:#fdecea;color:#8a2c1f;border-radius:9px;padding:13px 16px;margin-bottom:16px}.ok{background:#E1F0E6;color:#15573F;border-radius:12px;padding:22px}
.ok h1{font-size:22px;margin:0 0 8px}.hash{font-size:11px;color:#6d8174;overflow-wrap:anywhere;margin-top:14px}
.kit-lista{display:flex;flex-direction:column;border:1px solid #dfe7e1;border-radius:10px;overflow:hidden}.kit-item{display:flex;gap:14px;padding:12px 14px;border-bottom:1px solid #edf2ee}.kit-item:last-child{border-bottom:0}.kit-item>span{flex-shrink:0;width:26px;height:26px;border-radius:50%;background:#e4efe7;color:#174c37;font-size:12px;font-weight:700;display:flex;align-items:center;justify-content:center}.kit-item div{display:flex;flex-direction:column;gap:2px;min-width:0}.kit-item strong{font-size:15px}.kit-item small{font-size:13px;color:#4f6658;overflow-wrap:anywhere}@media(max-width:560px){dl{grid-template-columns:1fr}.card{padding:20px}}
</style></head><body>
<header class="top"><div><img src="{{ url_for('identidade_visual', nome='icmbio') }}" alt="ICMBio"><div><strong>Patrimônio Carajás</strong><span>NGI ICMBio Carajás · Gestão patrimonial</span></div></div></header>
<main>
{% if estado == 'invalido' %}<section class="card"><h1 style="font-size:21px;margin-top:0">Link indisponível</h1><p>{{ mensagem }}</p><p>Se você ainda precisa dar o aceite, peça ao setor de Patrimônio do NGI ICMBio Carajás um novo link.</p></section>
{% elif estado == 'concluido' %}<section class="card"><div class="ok"><h1>{{ 'Aceite registrado.' if aceite.status == 'Aceito' else 'Recusa registrada.' }}</h1>
<p>{% if aceite.status == 'Aceito' %}Obrigado, {{ aceite.nome_digitado }}. O seu aceite do {{ doc.tipo|lower }} DOC-{{ '%06d'|format(doc.id) }} foi registrado em {{ aceite.respondido_em|datahora }}.{% else %}O setor de Patrimônio foi avisado de que você não concorda com o termo DOC-{{ '%06d'|format(doc.id) }} e entrará em contato.{% endif %}</p>
<p style="margin-bottom:0">{% if aceite.status == 'Aceito' %}Uma confirmação foi enviada para {{ aceite.email }}. Você já pode fechar esta página.{% endif %}</p></div>
<p class="hash">Comprovante ACE-{{ '%06d'|format(aceite.id) }} · SHA-256 {{ aceite.comprovante }}</p></section>
{% else %}
<section class="saudacao"><span class="eyebrow">Aceite eletrônico</span><h1>Olá, {{ aceite.nome_destinatario }}.</h1><p>Leia o termo abaixo com atenção. No final da página, confirme com o seu nome.</p></section>
{% include 'tdoc_artigo' %}
<section class="card">{% for e in erros %}<div class="erro" role="alert">{{ e }}</div>{% endfor %}
<form method="post"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><input type="hidden" name="acao" value="aceitar">
<h2 style="margin-top:0">Confirmar o recebimento</h2><label for="nome-aceite">Seu nome completo</label><input type="text" id="nome-aceite" name="nome" required minlength="5" maxlength="160" autocomplete="name" value="{{ nome_informado }}"><small class="dica">Digite seu nome como forma de assinatura.</small>
<div class="check"><input type="checkbox" id="concordo" name="concordo" value="sim" required><label for="concordo" style="font-weight:400">Li o termo acima e concordo com a declaração de responsabilidade.</label></div>
<button class="btn" type="submit">Aceitar o termo</button></form>
<details{{ ' open' if recusa_aberta }}><summary>Não concordo com este termo</summary><form method="post"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><input type="hidden" name="acao" value="recusar">
<label for="nome-recusa" style="display:block;margin-top:14px">Seu nome completo</label><input type="text" id="nome-recusa" name="nome" required minlength="5" maxlength="160" autocomplete="name" value="{{ nome_informado }}">
<label for="motivo">Explique o motivo</label><textarea id="motivo" name="motivo" required minlength="10" maxlength="2000" placeholder="Ex.: não recebi este bem; o número de série não confere.">{{ motivo_informado }}</textarea>
<button class="btn sec" type="submit">Registrar que não concordo</button></form></details>
<p class="hash">Ao confirmar, o sistema registra data, hora, endereço IP e navegador, junto do código de integridade do termo ({{ doc.integridade[:16] }}…).</p></section>
{% endif %}</main></body></html>"""


def tela_aceite(estado, status=200, **dados):
    dados.setdefault('erros', [])
    dados.setdefault('nome_informado', '')
    dados.setdefault('motivo_informado', '')
    dados.setdefault('recusa_aberta', False)
    return render_template_string(ACEITE_TEMPLATE, estado=estado, **dados), status


def buscar_aceite(codigo, bloquear=False):
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', codigo):
        return None
    consulta = select(AceiteTermo).where(AceiteTermo.token_hash == digest('aceite:' + codigo))
    if bloquear:
        consulta = consulta.with_for_update().execution_options(populate_existing=True)
    return db.session.scalar(consulta)


@app.route('/aceite/<codigo>', methods=['GET', 'POST'])
def aceite_termo(codigo):
    if request.method == 'POST' and not limitar_recuperacao('', finalidade='aceite'):
        return tela_aceite('invalido', 429, mensagem='Muitas tentativas a partir desta conexão. Aguarde 15 minutos e tente novamente.')
    aceite = buscar_aceite(codigo, bloquear=request.method == 'POST')
    doc = db.session.get(Documento, aceite.documento_id) if aceite else None
    if not aceite or not doc:
        db.session.rollback()
        return tela_aceite('invalido', 404, mensagem='Este link de aceite não existe ou foi digitado incompleto.')
    if aceite.status in ('Aceito', 'Recusado'):
        db.session.rollback()
        return tela_aceite('invalido', 400, mensagem='Este termo já foi respondido por este link em ' + datahora(aceite.respondido_em) + '.')
    if aceite.situacao != 'Pendente':
        db.session.rollback()
        motivo = 'expirou' if aceite.situacao == 'Expirado' else 'foi substituído por um envio mais recente ou cancelado'
        return tela_aceite('invalido', 400, mensagem=f'Este link {motivo}.')
    if aceite.integridade_documento != doc.integridade:
        db.session.rollback()
        return tela_aceite('invalido', 400, mensagem='O conteúdo do termo foi alterado depois do envio. Peça um novo link.')
    comum = dict(aceite=aceite, declaracao=texto_declaracao_aceite(doc), **contexto_termo(doc))
    if request.method == 'GET':
        if aceite.visualizado_em is None:
            aceite.visualizado_em = datetime.now(timezone.utc)
            db.session.commit()
        return tela_aceite('formulario', **comum)
    acao = request.form.get('acao', '')
    nome = ' '.join(request.form.get('nome', '').split())[:160]
    motivo = request.form.get('motivo', '').strip()[:2000]
    erros = []
    if acao not in ('aceitar', 'recusar'):
        erros.append('Escolha aceitar ou registrar que não concorda.')
    if len(nome) < 5:
        erros.append('Digite seu nome completo.')
    if acao == 'aceitar' and request.form.get('concordo') != 'sim':
        erros.append('Marque a confirmação de que leu e concorda com o termo.')
    if acao == 'recusar' and len(motivo) < 10:
        erros.append('Explique o motivo com pelo menos 10 caracteres.')
    if erros:
        db.session.rollback()
        return tela_aceite('formulario', 422, erros=erros, nome_informado=nome, motivo_informado=motivo,
                           recusa_aberta=acao == 'recusar', **comum)
    agora = datetime.now(timezone.utc)
    aceite.status = 'Aceito' if acao == 'aceitar' else 'Recusado'
    aceite.respondido_em = agora
    aceite.nome_digitado = nome
    aceite.motivo_recusa = motivo if acao == 'recusar' else ''
    aceite.ip = (request.remote_addr or '')[:64]
    aceite.user_agent = request.headers.get('User-Agent', '')[:300]
    evidencia = dict(aceite=aceite.id, documento=doc.id, tipo=doc.tipo, integridade_documento=doc.integridade,
                     email=aceite.email, nome=nome, decisao=aceite.status, motivo=aceite.motivo_recusa,
                     respondido_em=agora.isoformat(), ip=aceite.ip, navegador=aceite.user_agent)
    aceite.comprovante = hashlib.sha256(json.dumps(evidencia, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    for bem_id in ids_bens_documento(doc):
        bem = db.session.get(Bem, bem_id)
        if bem:
            db.session.add(EventoBem(bem_id=bem.id, usuario_id=aceite.enviado_por,
                acao='Termo aceito eletronicamente' if acao == 'aceitar' else 'Termo recusado pelo responsável',
                detalhes=json.dumps({'antes': None, 'depois': snapshot(bem)}, ensure_ascii=False)))
    db.session.commit()
    numero = numero_documento(doc)
    try:
        if acao == 'aceitar':
            enviar_email_sistema(aceite.email, f'Aceite registrado · {numero} · Patrimônio Carajás',
                f'Olá, {nome}.\n\nSeu aceite do {doc.tipo.lower()} {numero} foi registrado em {datahora(agora)}.\n'
                f'Comprovante ACE-{aceite.id:06d} · SHA-256 {aceite.comprovante}\n\nGuarde este e-mail. NGI ICMBio Carajás')
    except (OSError, smtplib.SMTPException, ValueError):
        app.logger.warning('Confirmação de aceite não enviada ao destinatário.')
    remetente = db.session.get(Usuario, aceite.enviado_por)
    if remetente and remetente.email:
        try:
            situacao = 'aceitou' if acao == 'aceitar' else 'NÃO concordou com'
            enviar_email_sistema(remetente.email, f'{nome} {situacao} o {numero} · Patrimônio Carajás',
                f'{nome} ({aceite.email}) {situacao} o {doc.tipo.lower()} {numero} em {datahora(agora)}.\n'
                + (f'Motivo informado: {motivo}\n' if acao == 'recusar' else '')
                + f'\nAbra o documento: {PUBLIC_URL}{url_for("documento_detalhe", documento_id=doc.id)}\n\nPatrimônio Carajás')
        except (OSError, smtplib.SMTPException, ValueError):
            app.logger.warning('Aviso de resposta do aceite não enviado ao emitente.')
    return tela_aceite('concluido', doc=doc, aceite=aceite)


@app.route('/baixas', methods=['GET', 'POST'])
@login_obrigatorio
def baixas():
    formulario = request.method == 'POST' or request.args.get('aba') == 'cadastro'
    if formulario and g.usuario.leitura:
        abort(403)
    erros = []
    if request.method == 'POST':
        repetida = validar_token_operacao()
        if repetida is not None:
            return repetida
        try:
            chave = inteiro(request.form.get('bem_id'))
            if not chave:
                raise ValueError('Selecione um bem.')
            bem = trava_bem(chave)
            if movimento_pendente(bem.id) or entrega_aberta(bem.id):
                raise ValueError(
                    'Conclua a movimentação ou a devolução temporária antes de solicitar baixa.'
                )
            if processo_aberto(bem.id):
                raise ValueError('Já existe um processo em análise para este bem.')
            motivo = request.form.get('motivo', '')
            if motivo not in MOTIVOS_BAIXA:
                erros.append('Escolha um motivo válido.')
            valores = {
                campo: texto_campo(request.form, campo, rotulo, limite, erros, minimo)
                for campo, rotulo, limite, minimo in (
                    ('justificativa', 'Justificativa', 5000, 10),
                    ('processo', 'Processo administrativo', 200, 3),
                    ('titularidade', 'Titular / proprietário', 160, 2),
                    ('destinacao', 'Destinação proposta', 300, 3),
                    ('avaliacao', 'Referência da avaliação / comissão', 300, 0),
                )
            }
            if erros:
                raise ValueError('Confira os dados do processo.')
            obj = ProcessoBaixa(
                bem_id=bem.id,
                motivo=motivo,
                retrato=snapshot(bem),
                criado_por=g.usuario.id,
                criado_nome=g.usuario.nome,
                **valores,
            )
            db.session.add(obj)
            db.session.flush()
            doc = criar_documento(
                'Solicitação de encerramento / baixa',
                bem,
                dict(valores, motivo=motivo),
                f'BAI-{obj.id:06d} · {bem.nome}',
            )
            # Documento da solicitação é preservado separado da conclusão.
            doc.solicitacao_baixa_id = obj.id
            doc.dados = dict(doc.dados, processo_baixa=obj.id)
            doc.integridade = hashlib.sha256(
                json.dumps(doc.dados, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest()
            flash('Solicitação aberta. O bem continua no acervo até a conclusão por administrador.')
            return finalizar_operacao(url_for('baixa_detalhe', baixa_id=obj.id))
        except ValueError as e:
            db.session.rollback()
            erros.append(str(e))
    if formulario:
        return tela_operacao(
            'baixas',
            'baixa_form',
            'Encerramento e baixa',
            status=422 if erros else 200,
            valores=request.form if request.method == 'POST' else request.args,
            erros=erros,
            operacao_token=token_operacao(),
            motivos_baixa=MOTIVOS_BAIXA,
            grupos_motivos_baixa=GRUPOS_MOTIVOS_BAIXA,
            **busca_bem_selecionado(),
        )
    filtro = request.args.get('status', '')
    q = request.args.get('q', '').strip()[:120]
    consulta = select(ProcessoBaixa)
    if filtro in ('Em análise', 'Concluída', 'Indeferida', 'Cancelada'):
        consulta = consulta.where(ProcessoBaixa.status == filtro)
    if q:
        consulta = consulta.where(
            or_(
                ProcessoBaixa.processo.icontains(q, autoescape=True),
                ProcessoBaixa.titularidade.icontains(q, autoescape=True),
            )
        )
    return tela_operacao(
        'baixas',
        'baixa_lista',
        'Encerramento e baixa',
        q=q,
        filtro=filtro,
        **paginar_operacao(consulta.order_by(ProcessoBaixa.id.desc())),
    )


@app.get('/baixas/<int:baixa_id>')
@login_obrigatorio
def baixa_detalhe(baixa_id):
    obj=carregar(ProcessoBaixa,baixa_id)
    doc=db.session.scalar(select(Documento).where(Documento.baixa_id==obj.id))
    solicitacao=db.session.scalar(select(Documento).where(Documento.solicitacao_baixa_id==obj.id).order_by(Documento.id.desc()))
    return tela_operacao('baixas','baixa_detalhe','Processo de baixa',processo=obj,documento=doc,solicitacao=solicitacao)


@app.post('/baixas/<int:baixa_id>/decidir')
@login_obrigatorio
def decidir_baixa(baixa_id):
    if g.usuario.perfil != 'Administrador':
        abort(403)
    obj = carregar(ProcessoBaixa, baixa_id)
    bem = carregar(Bem, obj.bem_id, True)
    obj = carregar(ProcessoBaixa, baixa_id, True)
    if obj.status != 'Em análise':
        flash('Este processo já foi tratado.')
        return redirect(url_for('baixa_detalhe', baixa_id=obj.id))
    erros = []
    acao = request.form.get('acao', '')
    decisao = texto_campo(request.form, 'decisao', 'Decisão / fundamentação', 5000, erros, 10)
    autoridade = texto_campo(request.form, 'autoridade', 'Autoridade competente', 160, erros, 2)
    autorizacao = texto_campo(
        request.form, 'autorizacao', 'Referência da decisão / autorização', 300, erros, 3
    )
    if acao not in ('concluir', 'indeferir', 'cancelar'):
        erros.append('Selecione uma ação válida.')
    if acao == 'concluir':
        if request.form.get('confirmar') != 'sim':
            erros.append(
                'Confirme a conclusão documental do procedimento e a autorização da autoridade competente.'
            )
        if bem.encerrado or movimento_pendente(bem.id) or entrega_aberta(bem.id):
            erros.append('Há impedimento no bem ou em suas movimentações.')
        # A documentação de suporte fica vinculada à solicitação.
        docs = db.session.scalars(
            select(Documento.id).where(Documento.solicitacao_baixa_id == obj.id)
        ).all()
        if not docs or not db.session.scalar(
            select(AnexoDocumento.id).where(AnexoDocumento.documento_id.in_(docs)).limit(1)
        ):
            erros.append(
                'Anexe pelo menos um documento de suporte na solicitação antes de concluir.'
            )
    if erros:
        db.session.rollback()
        for erro in erros:
            flash(erro)
        return redirect(url_for('baixa_detalhe', baixa_id=obj.id))
    obj.status = {'concluir': 'Concluída', 'indeferir': 'Indeferida', 'cancelar': 'Cancelada'}[acao]
    obj.decisao = decisao
    obj.autoridade = autoridade
    obj.autorizacao = autorizacao
    obj.concluido_por = g.usuario.id
    obj.concluido_em = datetime.now(timezone.utc)
    if acao == 'concluir':
        antes = snapshot(bem)
        bem.encerrado = True
        bem.encerrado_em = datetime.now(timezone.utc)
        bem.conferido = False
        bem.revisao += 1
        bem.atualizado_em = datetime.now(timezone.utc)
        registrar_evento(bem, 'Encerramento / baixa', antes)
        criar_documento(
            'Registro de encerramento / baixa',
            bem,
            dict(
                processo=obj.processo,
                motivo=obj.motivo,
                justificativa=obj.justificativa,
                titularidade=obj.titularidade,
                destinacao=obj.destinacao,
                avaliacao=obj.avaliacao,
                decisao=decisao,
                autoridade=autoridade,
                autorizacao=autorizacao,
            ),
            bem.nome,
            baixa=obj,
        )
    db.session.commit()
    flash('Decisão registrada. O histórico do bem foi preservado.')
    return redirect(url_for('baixa_detalhe', baixa_id=obj.id))


@app.route('/inventario', methods=['GET', 'POST'])
@login_obrigatorio
def inventario():
    formulario = request.method == 'POST' or request.args.get('aba') == 'cadastro'
    if formulario and g.usuario.leitura:
        abort(403)
    erros = []
    if request.method == 'POST':
        repetida = validar_token_operacao()
        if repetida is not None:
            return repetida
        try:
            if db.engine.dialect.name == 'postgresql':
                db.session.execute(text('SELECT pg_advisory_xact_lock(739105639)'))
            if db.session.scalar(
                select(CampanhaInventario.id).where(CampanhaInventario.status == 'Aberto').limit(1)
            ):
                raise ValueError(
                    'Já existe um inventário aberto. Conclua-o antes de iniciar outro.'
                )
            nome = texto_campo(request.form, 'nome', 'Nome do inventário', 160, erros, 3)
            referencia = texto_campo(
                request.form, 'referencia', 'Portaria / processo / referência', 200, erros
            )
            comissao = texto_campo(request.form, 'comissao', 'Comissão / equipe', 1000, erros)
            prazo = None
            if request.form.get('prazo'):
                try:
                    prazo = date.fromisoformat(request.form['prazo'])
                    if prazo < hoje_local():
                        erros.append('O prazo da nova campanha deve ser igual ou posterior a hoje.')
                except ValueError:
                    erros.append('Informe uma data de prazo válida.')
            base_id = inteiro(request.form.get('base_id'))
            base = db.session.get(BaseLocal, base_id) if base_id else None
            if request.form.get('base_id') and (not base or not base.ativo):
                erros.append('Selecione uma base ativa.')
            convenio_inv_id = inteiro(request.form.get('convenio_id'))
            convenio_inv = db.session.get(Convenio, convenio_inv_id) if convenio_inv_id else None
            if request.form.get('convenio_id') and not convenio_inv:
                erros.append('Selecione um convênio da lista.')
            if erros:
                raise ValueError('Confira os dados do inventário.')
            consulta = (
                select(Bem).where(Bem.encerrado.is_(False)).order_by(Bem.id).with_for_update()
            )
            if base:
                consulta = consulta.where(Bem.base_id == base.id)
            if convenio_inv:
                consulta = consulta.where(Bem.convenio_id == convenio_inv.id)
            bens = db.session.scalars(consulta).all()
            if not bens:
                raise ValueError('Nenhum bem ativo encontrado no escopo selecionado.')
            inv = CampanhaInventario(
                nome=nome,
                referencia=referencia,
                prazo=prazo,
                comissao=comissao,
                base_id=base_id,
                convenio_id=convenio_inv.id if convenio_inv else None,
                local=(base.nome if base else 'Todos os locais') + (f' · {convenio_inv.nome}' if convenio_inv else ''),
                autor_id=g.usuario.id,
            )
            db.session.add(inv)
            db.session.flush()
            for bem in bens:
                db.session.add(
                    ItemInventario(inventario_id=inv.id, bem_id=bem.id, retrato=snapshot(bem))
                )
                bem.conferido = False
            flash(
                f'Inventário aberto com {len(bens)} bens. Novos cadastros não alteram este escopo.'
            )
            return finalizar_operacao(url_for('inventario_detalhe', inventario_id=inv.id))
        except ValueError as e:
            db.session.rollback()
            erros.append(str(e))
    if formulario:
        return tela_operacao(
            'inventario',
            'inv_form',
            'Inventário',
            status=422 if erros else 200,
            valores=request.form if request.method == 'POST' else {},
            erros=erros,
            operacao_token=token_operacao(),
            bases_destino=opcoes_bases(),
            convenios_inventario=db.session.scalars(select(Convenio).order_by(Convenio.nome)).all(),
        )
    if request.args.get('aba') != 'anteriores':
        campanha = db.session.scalar(
            select(CampanhaInventario)
            .order_by(
                case((CampanhaInventario.status == 'Aberto', 0), else_=1),
                CampanhaInventario.id.desc(),
            )
            .limit(1)
        )
        return painel_inventario(campanha)
    return tela_operacao(
        'inventario',
        'inv_lista',
        'Inventários anteriores',
        **paginar_operacao(
            select(CampanhaInventario)
            .where(CampanhaInventario.status == 'Encerrado')
            .order_by(CampanhaInventario.id.desc())
        ),
    )


@app.get('/inventario/<int:inventario_id>')
@login_obrigatorio
def inventario_detalhe(inventario_id):
    inv=carregar(CampanhaInventario,inventario_id)
    consulta,q,filtro,local_filtro=consulta_inventario(inv)
    resumo=dict(db.session.execute(select(ItemInventario.status,func.count()).where(ItemInventario.inventario_id==inv.id).group_by(ItemInventario.status)).all())
    campo_local=func.coalesce(func.nullif(ItemInventario.retrato['local'].as_string(),''),'Local não informado')
    locais=db.session.scalars(select(campo_local).where(ItemInventario.inventario_id==inv.id).distinct().order_by(campo_local)).all()
    pagina=paginar_operacao(consulta.order_by(ItemInventario.id))
    ids=[item.bem_id for item in pagina['rows']]
    fotos=dict(db.session.execute(select(Bem.id,Bem.tem_foto).where(Bem.id.in_(ids))).all()) if ids else {}
    args=filtros_retorno_inventario()
    links_campo=db.session.scalars(select(LinkCampo).where(LinkCampo.inventario_id==inv.id,LinkCampo.ativo.is_(True)).order_by(LinkCampo.id.desc())).all()
    achados_campo=db.session.scalars(select(AchadoCampo).where(AchadoCampo.inventario_id==inv.id).order_by(AchadoCampo.id.desc())).all()
    return tela_operacao('inventario','inv_detalhe','Inventário',inv=inv,resumo=resumo,q=q,filtro=filtro,links_campo=links_campo,achados_campo=achados_campo,
        inv_locais=locais,local_filtro=local_filtro,fotos=fotos,retorno_args=args,
        link_relatorio=url_for('inventario_imprimir',inventario_id=inv.id,**{k:v for k,v in args.items() if k!='pagina'}),
        status_inventario=STATUS_INVENTARIO,**pagina)


def filtros_retorno_inventario():
    # Somente parâmetros conhecidos: nunca aceita URL arbitrária para redirecionamento.
    return {k:request.args.get(k,'')[:160] for k in ('q','status','local','ocorrencias','pagina') if request.args.get(k)}


def consulta_inventario(inv):
    q = request.args.get('q', '').strip()[:120]
    filtro = request.args.get('status', '')
    local_filtro = request.args.get('local', '').strip()[:160]
    consulta = select(ItemInventario).where(ItemInventario.inventario_id == inv.id)
    if local_filtro:
        consulta = consulta.where(
            func.coalesce(
                func.nullif(ItemInventario.retrato['local'].as_string(), ''), 'Local não informado'
            )
            == local_filtro
        )
    if request.args.get('ocorrencias') == 'sim':
        consulta = consulta.where(ItemInventario.status.in_(('Divergência', 'Não localizado')))
    if filtro in STATUS_INVENTARIO:
        consulta = consulta.where(ItemInventario.status == filtro)
    if q:
        consulta = consulta.where(
            or_(
                *(
                    ItemInventario.retrato[c].as_string().icontains(q, autoescape=True)
                    for c in ('nome', 'serie', 'plaqueta_original', 'numero_ngi')
                )
            )
        )
    return consulta, q, filtro, local_filtro


VALIDADES_LINK_CAMPO = (1, 3, 7, 15, 30)
TOLERANCIA_ENVIO_CAMPO = 7 * 86400  # depois de vencer, ainda recebe o que ficou guardado no celular


def qr_data_url(texto):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=3)
    qr.add_data(texto)
    qr.make(fit=True)
    out = io.BytesIO()
    qr.make_image(fill_color='black', back_color='white').save(out, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()


@app.post('/inventario/<int:inventario_id>/links-campo')
@login_obrigatorio
def criar_link_campo(inventario_id):
    if g.usuario.leitura:
        abort(403)
    inv = carregar(CampanhaInventario, inventario_id)
    if inv.status != 'Aberto':
        flash('Este inventário está encerrado. Não é possível gerar link de campo.')
        return redirect(url_for('inventario_detalhe', inventario_id=inv.id))
    dias = inteiro(request.form.get('dias')) or 7
    if dias not in VALIDADES_LINK_CAMPO:
        dias = 7
    local = request.form.get('local', '').strip()[:160]
    if local:
        campo_local = func.coalesce(func.nullif(ItemInventario.retrato['local'].as_string(), ''), 'Local não informado')
        existe = db.session.scalar(select(ItemInventario.id).where(ItemInventario.inventario_id == inv.id, campo_local == local).limit(1))
        if not existe:
            flash('Esse local não faz parte deste inventário.')
            return redirect(url_for('inventario_detalhe', inventario_id=inv.id))
    rotulo = ' '.join(request.form.get('rotulo', '').split())[:120]
    codigo = secrets.token_urlsafe(32)
    link = LinkCampo(inventario_id=inv.id, token_hash=digest('campo:' + codigo), rotulo=rotulo, local=local,
                     criado_por=g.usuario.id, criado_por_nome=g.usuario.nome, expira_em=int(time.time()) + dias * 86400)
    db.session.add(link)
    db.session.commit()
    url = PUBLIC_URL + url_for('campo_coleta', codigo=codigo)
    texto = (f'Conferência de patrimônio · {inv.nome}' + (f' · {local}' if local else '') +
             f'\n\n1) Abra este link agora, com internet, e digite seu nome.\n2) No campo, abra de novo o link e aponte a câmera para as plaquetas.\n3) Quando voltar a ter internet, tudo é enviado sozinho.\n\n{url}')
    return tela_operacao('inventario', 'inv_link_campo', 'Link da equipe de campo', inv=inv, link=link, link_url=url,
                         qr_link=qr_data_url(url), whatsapp='https://wa.me/?text=' + quote(texto))


@app.post('/inventario/links-campo/<int:link_id>/desativar')
@login_obrigatorio
def desativar_link_campo(link_id):
    if g.usuario.leitura:
        abort(403)
    link = carregar(LinkCampo, link_id, True)
    link.ativo = False
    db.session.commit()
    flash('Link de campo desativado. Quem tinha o link não consegue mais enviar conferências.')
    return redirect(url_for('inventario_detalhe', inventario_id=link.inventario_id) + '#equipe-campo')


def buscar_link_campo(codigo, bloquear=False):
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', codigo or ''):
        return None
    consulta = select(LinkCampo).where(LinkCampo.token_hash == digest('campo:' + codigo))
    if bloquear:
        consulta = consulta.with_for_update().execution_options(populate_existing=True)
    return db.session.scalar(consulta)


def itens_link_campo(link):
    campo_local = func.coalesce(func.nullif(ItemInventario.retrato['local'].as_string(), ''), 'Local não informado')
    consulta = select(ItemInventario).where(ItemInventario.inventario_id == link.inventario_id)
    if link.local:
        consulta = consulta.where(campo_local == link.local)
    return db.session.scalars(consulta.order_by(ItemInventario.id)).all()


CAMPO_TEMPLATE = r"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow"><meta name="theme-color" content="#0B3325"><meta name="mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-capable" content="yes">
<title>Conferência de campo · Patrimônio Carajás</title>
<style>
*{box-sizing:border-box}html,body{margin:0}body{background:#F4F5F1;color:#173f30;font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;padding-bottom:90px}
button{font:inherit;cursor:pointer}.oculto{display:none!important}
.topo{background:#0B3325;color:#fff;padding:16px 18px 14px;position:sticky;top:0;z-index:5}
.topo strong{display:block;font-size:17px}.topo small{font-size:13px;opacity:.85}
.sinal{display:flex;align-items:center;gap:8px;margin-top:10px;font-size:13px;background:#ffffff14;border-radius:8px;padding:8px 10px}
.sinal i{width:10px;height:10px;border-radius:50%;background:#c6f36b;flex-shrink:0}.sinal.off i{background:#f2b33d}
main{padding:16px;max-width:560px;margin:0 auto}
.progresso{background:#fff;border:1px solid #dfe7e1;border-radius:14px;padding:16px;margin-bottom:14px}
.progresso b{font-size:28px}.barra{height:10px;border-radius:10px;background:#e8eee9;overflow:hidden;margin-top:8px}.barra span{display:block;height:100%;background:#1f6b4c;border-radius:10px}
.grande{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;border:0;border-radius:14px;padding:18px;font-size:18px;font-weight:700;background:#0E3B2B;color:#fff;margin-bottom:10px}
.sec{display:flex;width:100%;justify-content:center;border:1px solid #bfd0c4;background:#fff;color:#173f30;border-radius:12px;padding:14px;font-weight:600;margin-bottom:10px}
.camera{position:fixed;inset:0;background:#000;z-index:20;display:flex;flex-direction:column}
.camera video{flex:1;width:100%;object-fit:cover}.mira{position:absolute;left:50%;top:42%;width:62vw;max-width:300px;aspect-ratio:1;transform:translate(-50%,-50%);border:3px solid #c6f36b;border-radius:18px;box-shadow:0 0 0 2000px #0006}
.camera p{position:absolute;left:0;right:0;top:calc(42% + min(31vw,150px) + 16px);text-align:center;color:#fff;font-size:15px;margin:0;padding:0 20px}
.camera .fechar{position:absolute;left:16px;right:16px;bottom:24px;border:0;border-radius:12px;padding:16px;background:#fff;color:#173f30;font-weight:700}
.cartao{position:fixed;left:0;right:0;bottom:0;z-index:30;background:#fff;border-radius:20px 20px 0 0;padding:20px 18px 26px;box-shadow:0 -10px 40px #0004;max-height:88vh;overflow:auto}
.cartao h2{margin:0 0 4px;font-size:20px}.cartao .meta{color:#4f6658;font-size:14px;margin:0 0 12px}
.dl{display:grid;grid-template-columns:110px 1fr;gap:6px 10px;font-size:14px;background:#f3f8f4;border-radius:10px;padding:12px;margin-bottom:14px}.dl span{color:#5b7365}
.ok{background:#1f6b4c}.dif{background:#c07a12}.nao{background:#a63d36}
.acoes button{display:block;width:100%;border:0;border-radius:12px;padding:16px;font-size:17px;font-weight:700;color:#fff;margin-bottom:10px}
.acoes .voltar{background:#eef2ef;color:#173f30}
.motivos{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 10px}.motivos button{border:1px solid #bfd0c4;background:#fff;border-radius:20px;padding:9px 14px;font-size:14px;color:#173f30}
.motivos button.sel{background:#173f30;color:#fff;border-color:#173f30}
textarea,input[type=text],input[type=search]{width:100%;font:16px system-ui,sans-serif;padding:12px 14px;border:1px solid #bfd0c4;border-radius:10px;color:#173f30;background:#fff}
textarea{min-height:84px}
.aviso{background:#fff4de;color:#7a4d00;border-radius:10px;padding:12px 14px;font-size:14px;margin-bottom:12px}
.selo{display:inline-block;font-size:12px;font-weight:700;border-radius:20px;padding:3px 10px;background:#e4efe7;color:#174c37}.selo.dif{background:#fff1d6;color:#7a4d00}.selo.nao{background:#fde3df;color:#8a1c12}.selo.fila{background:#e8edf9;color:#2b4a9a}
.abas{display:flex;gap:8px;margin:18px 0 10px}.abas button{flex:1;border:1px solid #bfd0c4;background:#fff;border-radius:10px;padding:10px;font-weight:600;color:#173f30}.abas button.sel{background:#173f30;color:#fff;border-color:#173f30}
.lista{list-style:none;padding:0;margin:10px 0 0}.lista li{background:#fff;border:1px solid #e1e9e3;border-radius:12px;padding:12px 14px;margin-bottom:8px;display:flex;justify-content:space-between;gap:10px;align-items:center}
.lista li div{min-width:0}.lista strong{display:block;font-size:15px;overflow-wrap:anywhere}.lista small{display:block;color:#5b7365;font-size:13px;overflow-wrap:anywhere}
.lista button{border:1px solid #e3b9b1;background:#fff;color:#8a2c1f;border-radius:10px;padding:8px 10px;font-size:13px;white-space:nowrap}
.toast{position:fixed;left:16px;right:16px;bottom:20px;z-index:40;background:#173f30;color:#fff;border-radius:12px;padding:14px 16px;text-align:center;font-weight:600}
.fundo{position:fixed;inset:0;background:#0007;z-index:25}
.nome-box{position:fixed;inset:0;z-index:50;background:#F4F5F1;padding:30px 20px}.nome-box h1{font-size:22px}
.erro-box{background:#fff;border-radius:14px;padding:24px;margin:30px 16px;border:1px solid #dfe7e1}
</style></head><body>
{% if erro %}<div class="topo"><strong>Patrimônio Carajás</strong><small>Conferência de campo</small></div><div class="erro-box"><h1 style="font-size:20px;margin-top:0">Link indisponível</h1><p>{{ erro }}</p><p>Se você tem conferências guardadas neste celular, abra o link de novo quando o responsável liberar um novo link.</p></div></body></html>{% else %}
<div class="topo"><strong>{{ inv.nome }}</strong><small>{{ link.local or inv.local }}{% if link.rotulo %} · {{ link.rotulo }}{% endif %}</small><div class="sinal" id="sinal"><i></i><span id="sinal-txt">Verificando…</span></div></div>
<main>
<div class="progresso"><div><b id="p-feitos">0</b> de <span id="p-total">0</span> bens conferidos</div><div class="barra"><span id="p-barra" style="width:0%"></span></div><small id="p-pessoa" style="color:#5b7365"></small></div>
<button class="grande" id="btn-ler" type="button">📷 Ler QR Code da plaqueta</button>
<button class="sec" id="btn-fora" type="button">Encontrei um bem que não está na lista</button>
<div class="abas"><button type="button" class="sel" data-aba="faltam">Faltam <span id="n-faltam"></span></button><button type="button" data-aba="feitos">Conferidos <span id="n-feitos"></span></button></div>
<input type="search" id="busca" placeholder="Procurar por nome, plaqueta ou série" autocomplete="off">
<ul class="lista" id="lista"></ul>
</main>
<div class="camera oculto" id="camera"><video id="video" playsinline muted></video><div class="mira"></div><p id="camera-txt">Aponte para o QR Code da plaqueta</p><button class="fechar" id="camera-fechar" type="button">Fechar câmera</button></div>
<div class="fundo oculto" id="fundo"></div><div class="cartao oculto" id="cartao"></div>
<div class="nome-box oculto" id="nome-box"><h1>Antes de começar</h1><p>Digite seu nome. Ele aparece no registro de cada bem que você conferir.</p><input type="text" id="nome-input" maxlength="80" autocomplete="name" placeholder="Seu nome completo"><p></p><button class="grande" id="nome-ok" type="button">Começar</button><p style="color:#5b7365;font-size:14px">Depois deste passo, a lista de bens fica guardada no celular e funciona mesmo sem internet.</p></div>
<div class="toast oculto" id="toast"></div>
<script id="dados-servidor" type="application/json">{{ dados|tojson }}</script>
<script>
(function(){
const TOKEN={{ codigo|tojson }}, ENVIO={{ url_envio|tojson }}, JSQR='/static/vendor/jsQR.js';
const K=k=>'campo:'+TOKEN+':'+k;
const ler=(k,d)=>{try{const v=localStorage.getItem(K(k));return v===null?d:JSON.parse(v);}catch(e){return d;}};
const gravar=(k,v)=>{try{localStorage.setItem(K(k),JSON.stringify(v));return true;}catch(e){return false;}};
const $=id=>document.getElementById(id);
let servidor=JSON.parse($('dados-servidor').textContent);
let dados=ler('dados',null);
if(!dados||servidor.gerado>dados.gerado){dados=servidor;gravar('dados',dados);}
let fila=ler('fila',[]), feitos=ler('feitos',{}), nome=ler('nome',''), aba='faltam', enviando=false;
const uid=()=>Date.now().toString(36)+Math.random().toString(36).slice(2,10);
const norm=t=>String(t||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/\s+/g,' ').trim();
const itemPorId={};dados.itens.forEach(i=>itemPorId[i.id]=i);
function estado(i){const f=feitos[i.id];return f?f.status:i.status;}
function toast(t){const e=$('toast');e.textContent=t;e.classList.remove('oculto');clearTimeout(toast.t);toast.t=setTimeout(()=>e.classList.add('oculto'),2600);}
function esc(t){return String(t==null?'':t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function sinal(){const on=navigator.onLine;$('sinal').classList.toggle('off',!on);const n=fila.length;
 $('sinal-txt').textContent=(on?'Com internet':'Sem internet')+' · '+(n?n+(n===1?' registro guardado':' registros guardados')+(on?', enviando…':' no celular'):'tudo enviado');}
function render(){const total=dados.itens.length;const feitosN=dados.itens.filter(i=>estado(i)!=='Pendente').length;
 $('p-feitos').textContent=feitosN;$('p-total').textContent=total;$('p-barra').style.width=(total?feitosN/total*100:0)+'%';
 $('p-pessoa').textContent=nome?'Conferindo como '+nome:'';
 const q=norm($('busca').value);const lista=dados.itens.filter(i=>(aba==='faltam')===(estado(i)==='Pendente')).filter(i=>!q||norm([i.nome,i.patrimonio,i.serie,i.marca,i.modelo,i.responsavel].join(' ')).includes(q));
 $('n-faltam').textContent='('+dados.itens.filter(i=>estado(i)==='Pendente').length+')';$('n-feitos').textContent='('+feitosN+')';
 $('lista').innerHTML=lista.slice(0,300).map(i=>{const st=estado(i);const cls=st==='Conferido'?'':st==='Divergência'?'dif':'nao';const naFila=fila.some(f=>f.item_id===i.id);
  return '<li><div><strong>'+esc(i.nome)+'</strong><small>'+esc(i.patrimonio)+(i.serie?' · Série '+esc(i.serie):'')+'</small><small>'+esc(i.responsavel||'')+'</small>'+(st!=='Pendente'?'<span class="selo '+cls+'">'+esc(st)+'</span> ':'')+(naFila?'<span class="selo fila">guardado no celular</span>':'')+'</div>'+
  (st==='Pendente'?'<button type="button" data-abrir="'+i.id+'">Abrir</button>':'<button type="button" data-abrir="'+i.id+'" style="color:#173f30;border-color:#bfd0c4">Ver</button>')+'</li>';}).join('')||'<li><div><small>'+(aba==='faltam'?'Nenhum bem pendente aqui.':'Nenhum bem conferido ainda.')+'</small></div></li>';
 sinal();}
function fecharCartao(){$('cartao').classList.add('oculto');$('fundo').classList.add('oculto');}
function mostrarCartao(html){$('cartao').innerHTML=html;$('cartao').classList.remove('oculto');$('fundo').classList.remove('oculto');$('cartao').scrollTop=0;}
function salvar(item,status,obs){const reg={id:uid(),tipo:'conf',item_id:item.id,status:status,observacao:obs,quando:new Date().toISOString()};
 fila=fila.filter(f=>!(f.tipo==='conf'&&f.item_id===item.id));fila.push(reg);feitos[item.id]={status:status};
 const okF=gravar('fila',fila);gravar('feitos',feitos);fecharCartao();render();toast(okF?'Salvo no celular ✓':'Atenção: o celular está sem espaço');enviar();}
function cartaoItem(item,lido){const st=estado(item);
 mostrarCartao('<h2>'+esc(item.nome)+'</h2><p class="meta">'+esc(item.patrimonio)+(lido?' · lido pela câmera':'')+'</p>'+
 (st!=='Pendente'?'<div class="aviso">Este bem já está como <b>'+esc(st)+'</b>. Se precisar, registre de novo.</div>':'')+
 '<div class="dl"><span>Marca/modelo</span><b>'+esc([item.marca,item.modelo].filter(Boolean).join(' ')||'—')+'</b><span>Série</span><b>'+esc(item.serie||'—')+'</b><span>Local</span><b>'+esc(item.local||'—')+(item.complemento?' · '+esc(item.complemento):'')+'</b><span>Responsável</span><b>'+esc(item.responsavel||'—')+'</b><span>Conservação</span><b>'+esc(item.conservacao||'—')+'</b></div>'+
 '<p style="margin:0 0 10px;font-weight:600">O bem está assim?</p><div class="acoes"><button type="button" class="ok" id="c-ok">✓ Está tudo certo</button><button type="button" class="dif" id="c-dif">Tem algo diferente</button><button type="button" class="nao" id="c-nao">Não encontrei este bem</button><button type="button" class="voltar" id="c-voltar">Voltar</button></div>');
 $('c-ok').onclick=()=>salvar(item,'Conferido','');
 $('c-voltar').onclick=fecharCartao;
 $('c-dif').onclick=()=>motivos(item,'Divergência',['Está em outra sala ou local','Está com outra pessoa','Está danificado ou quebrado','Plaqueta ilegível ou faltando','Outro']);
 $('c-nao').onclick=()=>motivos(item,'Não localizado',['Procurei no local e não encontrei','Pode estar com outra pessoa','Outro']);}
function motivos(item,status,ops){let escolhido='';
 mostrarCartao('<h2>'+esc(item.nome)+'</h2><p class="meta">'+(status==='Divergência'?'O que está diferente?':'Não encontrei este bem')+'</p><div class="motivos">'+ops.map((o,n)=>'<button type="button" data-m="'+n+'">'+esc(o)+'</button>').join('')+'</div><textarea id="m-obs" maxlength="1000" placeholder="Detalhe se quiser (ex.: está na sala 3, com a Maria)"></textarea><p></p><div class="acoes"><button type="button" class="'+(status==='Divergência'?'dif':'nao')+'" id="m-salvar">Salvar</button><button type="button" class="voltar" id="m-voltar">Voltar</button></div>');
 document.querySelectorAll('[data-m]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-m]').forEach(x=>x.classList.remove('sel'));b.classList.add('sel');escolhido=ops[+b.dataset.m];});
 $('m-voltar').onclick=()=>cartaoItem(item,false);
 $('m-salvar').onclick=()=>{const det=$('m-obs').value.trim();if(!escolhido&&det.length<3){toast('Escolha uma opção ou escreva o que aconteceu');return;}
  salvar(item,status,[escolhido==='Outro'?'':escolhido,det].filter(Boolean).join(': '));};}
function cartaoFora(codigo){mostrarCartao('<h2>Bem fora da lista</h2><p class="meta">'+(codigo?'Este código não está na lista desta conferência.':'Registre um bem que você encontrou e que não está na lista.')+'</p>'+(codigo?'<div class="dl"><span>Código lido</span><b style="overflow-wrap:anywhere">'+esc(codigo)+'</b></div>':'')+
 '<textarea id="f-desc" maxlength="1000" placeholder="O que é e onde está (ex.: notebook Dell sem plaqueta, sala 2)"></textarea><p></p><div class="acoes"><button type="button" class="dif" id="f-salvar">Registrar</button><button type="button" class="voltar" id="f-voltar">Voltar</button></div>');
 $('f-voltar').onclick=fecharCartao;
 $('f-salvar').onclick=()=>{const d=$('f-desc').value.trim();if(d.length<5){toast('Descreva o bem em poucas palavras');return;}
  fila.push({id:uid(),tipo:'achado',descricao:d,codigo:codigo||'',quando:new Date().toISOString()});gravar('fila',fila);fecharCartao();render();toast('Salvo no celular ✓');enviar();};}
function achar(texto){const m=String(texto).match(/\/bem\/(\d+)/);if(m){const it=dados.itens.find(i=>String(i.bem_id)===m[1]);if(it)return it;}
 const t=norm(texto);const p=/^\d{1,9}$/.test(t)?String(+t).padStart(4,'0'):null;return dados.itens.find(i=>[i.numero_ngi,i.plaqueta_original,i.serie].some(v=>v&&norm(v)===t)||(p&&i.numero_ngi===p))||null;}
let stream=null,detector=null,lendo=false;
function carregarJsQR(){return window.jsQR?Promise.resolve():new Promise((ok,erro)=>{const s=document.createElement('script');s.src=JSQR;s.onload=ok;s.onerror=erro;document.head.appendChild(s);});}
async function abrirCamera(){
 if(!navigator.mediaDevices||!navigator.mediaDevices.getUserMedia){toast('Este celular não permite usar a câmera aqui. Use a busca pelo nome.');return;}
 try{stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'}},audio:false});}catch(e){toast('Permita o uso da câmera para ler o QR Code');return;}
 $('camera').classList.remove('oculto');const v=$('video');v.srcObject=stream;await v.play().catch(()=>{});
 detector=null;if('BarcodeDetector' in window){try{detector=new BarcodeDetector({formats:['qr_code']});}catch(e){detector=null;}}
 if(!detector){try{await carregarJsQR();}catch(e){toast('Leitor indisponível. Use a busca pelo nome.');fecharCamera();return;}}
 lendo=true;ciclo();}
function fecharCamera(){lendo=false;if(stream){stream.getTracks().forEach(t=>t.stop());stream=null;}$('camera').classList.add('oculto');}
const tela=document.createElement('canvas'),ctx=tela.getContext('2d',{willReadFrequently:true});
async function ciclo(){if(!lendo)return;const v=$('video');let txt=null;
 try{if(v.readyState>=2){if(detector){const r=await detector.detect(v);if(r.length)txt=r[0].rawValue;}
  else{const w=Math.min(v.videoWidth,720),h=Math.round(v.videoHeight*w/v.videoWidth);tela.width=w;tela.height=h;ctx.drawImage(v,0,0,w,h);const c=window.jsQR(ctx.getImageData(0,0,w,h).data,w,h,{inversionAttempts:'dontInvert'});if(c)txt=c.data;}}}catch(e){}
 if(txt){fecharCamera();if(navigator.vibrate)navigator.vibrate(80);const it=achar(txt);if(it)cartaoItem(it,true);else cartaoFora(txt);return;}
 setTimeout(ciclo,220);}
async function enviar(){if(enviando||!fila.length||!navigator.onLine){sinal();return;}enviando=true;sinal();
 const lote=fila.slice(0,200);
 try{const r=await fetch(ENVIO,{method:'POST',headers:{'Content-Type':'application/json','X-Campo':'1'},body:JSON.stringify({nome:nome,registros:lote}),credentials:'omit'});
  if(r.ok){const j=await r.json();const recebidos=new Set(j.recebidos||[]);fila=fila.filter(f=>!recebidos.has(f.id));gravar('fila',fila);
   if(j.itens){j.itens.forEach(s=>{if(itemPorId[s.id]){itemPorId[s.id].status=s.status;}});dados.gerado=Math.max(dados.gerado,j.gerado||0);gravar('dados',dados);}
   if(recebidos.size)toast('Conferências enviadas ✓');}
  else if(r.status===410||r.status===403||r.status===404){const j=await r.json().catch(()=>({}));toast(j.mensagem||'Link desativado. As conferências continuam guardadas no celular.');}
 }catch(e){}finally{enviando=false;render();if(fila.length&&navigator.onLine)setTimeout(enviar,15000);}}
$('btn-ler').onclick=abrirCamera;$('camera-fechar').onclick=fecharCamera;$('btn-fora').onclick=()=>cartaoFora('');$('fundo').onclick=fecharCartao;
document.querySelectorAll('[data-aba]').forEach(b=>b.onclick=()=>{aba=b.dataset.aba;document.querySelectorAll('[data-aba]').forEach(x=>x.classList.toggle('sel',x===b));render();});
$('busca').addEventListener('input',render);
$('lista').addEventListener('click',e=>{const b=e.target.closest('[data-abrir]');if(b)cartaoItem(itemPorId[b.dataset.abrir],false);});
function pedirNome(){$('nome-box').classList.remove('oculto');$('nome-input').focus();}
$('nome-ok').onclick=()=>{const n=$('nome-input').value.trim().replace(/\s+/g,' ');if(n.length<3){toast('Digite seu nome');return;}nome=n;gravar('nome',nome);$('nome-box').classList.add('oculto');render();};
window.addEventListener('online',()=>{sinal();enviar();});window.addEventListener('offline',sinal);
setInterval(enviar,30000);
if(!nome)pedirNome();
render();enviar();
if('serviceWorker' in navigator){navigator.serviceWorker.register('/campo/sw.js',{scope:'/campo/'}).catch(()=>{});}
if(window.caches&&navigator.onLine){caches.open('campo-v1').then(c=>{c.put(location.href,new Response('<!doctype html>'+document.documentElement.outerHTML.replace(/<script id="dados-servidor"[^>]*>[\s\S]*?<\/script>/,'<script id="dados-servidor" type="application/json">'+JSON.stringify(dados).replace(/</g,'\\u003c')+'<\/script>'),{headers:{'Content-Type':'text/html; charset=utf-8'}}));return c.add(JSQR);}).catch(()=>{});}
})();
</script></body></html>{% endif %}"""


def tela_campo(erro=None, status=200, **dados):
    return render_template_string(CAMPO_TEMPLATE, erro=erro, **dados), status


@app.get('/campo/sw.js')
def campo_sw():
    script = """const CACHE='campo-v1';
self.addEventListener('install',e=>{self.skipWaiting();e.waitUntil(caches.open(CACHE).then(c=>c.add('/static/vendor/jsQR.js')).catch(()=>{}));});
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('fetch',e=>{const r=e.request;if(r.method!=='GET')return;const u=new URL(r.url);if(u.origin!==location.origin)return;
 if(r.mode==='navigate'&&u.pathname.startsWith('/campo/')){e.respondWith(fetch(r).then(resp=>{if(resp.ok){const copia=resp.clone();caches.open(CACHE).then(c=>c.put(r,copia));}return resp;}).catch(()=>caches.match(r,{ignoreSearch:true}).then(m=>m||new Response('<h1>Sem internet</h1><p>Abra este link uma vez com internet antes de ir para o campo.</p>',{headers:{'Content-Type':'text/html; charset=utf-8'}}))));return;}
 if(u.pathname==='/static/vendor/jsQR.js'){e.respondWith(caches.match(r).then(m=>m||fetch(r)));}
});"""
    return Response(script, mimetype='application/javascript')


@app.get('/campo/<codigo>')
def campo_coleta(codigo):
    link = buscar_link_campo(codigo)
    inv = db.session.get(CampanhaInventario, link.inventario_id) if link else None
    if not link or not inv:
        return tela_campo('Este link de conferência não existe ou foi copiado incompleto.', 404)
    if not link.ativo:
        return tela_campo('Este link foi desativado pelo responsável pelo inventário.', 410)
    if inv.status != 'Aberto':
        return tela_campo('Este inventário já foi encerrado. Obrigado pela ajuda!', 410)
    if link.vencido:
        return tela_campo('Este link venceu. Peça um novo link ao responsável pelo inventário.', 410)
    itens = itens_link_campo(link)
    lista = []
    for item in itens:
        r = item.retrato or {}
        lista.append(dict(id=item.id, bem_id=item.bem_id, nome=r.get('nome') or '', status=item.status,
                          patrimonio=r.get('numero_ngi') or r.get('plaqueta_original') or 'Sem plaqueta',
                          numero_ngi=r.get('numero_ngi') or '', plaqueta_original=r.get('plaqueta_original') or '',
                          serie=r.get('serie') or '', marca=r.get('marca') or '', modelo=r.get('modelo') or '',
                          local=r.get('local') or '', complemento=r.get('complemento') or '',
                          responsavel=r.get('responsavel') or '', conservacao=r.get('conservacao') or ''))
    dados = dict(gerado=int(time.time() * 1000), itens=lista)
    return tela_campo(None, inv=inv, link=link, codigo=codigo, dados=dados,
                      url_envio=url_for('campo_enviar', codigo=codigo))


@csrf.exempt
@app.post('/campo/<codigo>/enviar')
def campo_enviar(codigo):
    # Sem sessão: a autorização é o próprio link secreto. Só aceita JSON do próprio sistema.
    if request.headers.get('X-Campo') != '1' or not request.is_json:
        return jsonify(mensagem='Requisição inválida.'), 400
    origem = request.headers.get('Origin')
    if origem and urlsplit(origem).netloc != request.host:
        return jsonify(mensagem='Origem não permitida.'), 403
    corpo = request.get_json(silent=True) or {}
    registros = corpo.get('registros') if isinstance(corpo.get('registros'), list) else []
    if len(registros) > 300:
        return jsonify(mensagem='Envio grande demais.'), 413
    pessoa = ' '.join(str(corpo.get('nome') or '').split())[:80] or 'Equipe de campo'
    link = buscar_link_campo(codigo)
    if not link:
        return jsonify(mensagem='Link inexistente.'), 404
    inv = carregar(CampanhaInventario, link.inventario_id, True)
    link = buscar_link_campo(codigo, bloquear=True)
    if not link.ativo:
        db.session.rollback()
        return jsonify(mensagem='Este link foi desativado. As conferências continuam guardadas no celular; procure o responsável.'), 410
    if inv.status != 'Aberto':
        db.session.rollback()
        return jsonify(mensagem='O inventário foi encerrado. Procure o responsável para registrar o que ficou no celular.'), 410
    if link.expira_em + TOLERANCIA_ENVIO_CAMPO <= int(time.time()):
        db.session.rollback()
        return jsonify(mensagem='O prazo deste link terminou. Procure o responsável pelo inventário.'), 410
    permitidos = {i.id: i for i in itens_link_campo(link)}
    recebidos, alterados = [], {}
    agora = datetime.now(timezone.utc)
    conferente = (pessoa + ' (campo)')[:120]
    for reg in registros:
        if not isinstance(reg, dict):
            continue
        rid = str(reg.get('id') or '')[:40]
        if not re.fullmatch(r'[a-z0-9]{6,40}', rid):
            continue
        if reg.get('tipo') == 'achado':
            descricao = ' '.join(str(reg.get('descricao') or '').split())[:1000]
            if len(descricao) < 5:
                recebidos.append(rid)
                continue
            ja = db.session.scalar(select(AchadoCampo.id).where(AchadoCampo.link_id == link.id, AchadoCampo.cliente_id == rid))
            if not ja:
                db.session.add(AchadoCampo(inventario_id=inv.id, link_id=link.id, cliente_id=rid, descricao=descricao,
                                           codigo=str(reg.get('codigo') or '')[:300], pessoa=pessoa))
            recebidos.append(rid)
            continue
        item = permitidos.get(inteiro(reg.get('item_id')))
        status = reg.get('status')
        if not item or status not in ('Conferido', 'Divergência', 'Não localizado'):
            recebidos.append(rid)  # registro que não pertence a este link: descarta para não travar a fila
            continue
        item = carregar(ItemInventario, item.id, True)
        bem = carregar(Bem, item.bem_id, True)
        obs = ' '.join(str(reg.get('observacao') or '').split())[:2500]
        if status == 'Conferido' and (bem.encerrado or str(bem.revisao) != (item.retrato or {}).get('revisao')):
            status = 'Divergência'
            obs = ('Cadastro alterado depois da abertura do inventário; bem encontrado no campo. ' + obs).strip()
        if status == 'Divergência' and len(obs) < 10:
            obs = ('Divergência apontada na conferência de campo. ' + obs).strip()
        if status == 'Não localizado' and len(obs) < 10:
            obs = ('Não encontrado na conferência de campo. ' + obs).strip()
        obs = (obs + f' [campo: {pessoa}]').strip() if status != 'Conferido' else (obs + (f' [campo: {pessoa}]' if obs else '')).strip()
        anterior = dict(status=item.status, observacao=item.observacao, conferente=item.conferente_nome)
        item.status = status
        item.observacao = obs[:3000]
        item.conferente_id = link.criado_por
        item.conferente_nome = conferente
        item.conferido_em = agora
        item.revisao += 1
        bem.conferido = status == 'Conferido' and not bem.encerrado
        db.session.add(EventoBem(bem_id=bem.id, usuario_id=link.criado_por, acao='Conferência de inventário',
            detalhes=json.dumps(dict(inventario=inv.id, campo=True, link=link.id, antes=anterior,
                                     depois=dict(status=status, observacao=item.observacao, conferente=conferente)), ensure_ascii=False)))
        alterados[item.id] = status
        recebidos.append(rid)
    if recebidos:
        link.envios += 1
        link.ultimo_envio = agora
    db.session.commit()
    estados = [dict(id=i, status=s) for i, s in db.session.execute(
        select(ItemInventario.id, ItemInventario.status).where(ItemInventario.id.in_(list(permitidos))))] if permitidos else []
    return jsonify(recebidos=recebidos, alterados=len(alterados), itens=estados, gerado=int(time.time() * 1000))


@app.get('/inventario/<int:inventario_id>/imprimir')
@login_obrigatorio
def inventario_imprimir(inventario_id):
    inv=carregar(CampanhaInventario,inventario_id)
    consulta,q,filtro,local_filtro=consulta_inventario(inv)
    # Sem paginação e sem fotografias binárias. Relatório usa o retrato da campanha.
    selecao=consulta.subquery()
    resumo=dict(db.session.execute(select(selecao.c.status,func.count()).group_by(selecao.c.status)).all())
    return render_template('inv_imprimir',inv=inv,rows=db.session.scalars(consulta.order_by(ItemInventario.id)),
        resumo=resumo,total=sum(resumo.values()),q=q,filtro=filtro,local_filtro=local_filtro,
        emitido=datetime.now(timezone.utc),voltar=url_for('inventario_detalhe',inventario_id=inv.id,**filtros_retorno_inventario()))


@app.route('/inventario/itens/<int:item_id>', methods=['GET', 'POST'])
@login_obrigatorio
def conferir_inventario(item_id):
    if g.usuario.leitura:
        abort(403)
    item = carregar(ItemInventario, item_id)
    # Fechamento e conferência serializados pela campanha.
    inv = carregar(CampanhaInventario, item.inventario_id, request.method == 'POST')
    item = carregar(ItemInventario, item_id, request.method == 'POST')
    bem = carregar(Bem, item.bem_id, request.method == 'POST')
    campo = request.args.get('campo') == 'sim'
    campo_local = request.args.get('local', '').strip()[:160]
    local_abertura = item.retrato.get('local') or 'Local não informado'
    if campo and campo_local and campo_local != local_abertura:
        flash(
            'Este bem não pertence ao local selecionado na abertura do inventário. Confira a base antes de continuar.'
        )
        return redirect(url_for('inventario_campo', inventario_id=inv.id, local=campo_local))
    erros = []
    if inv.status != 'Aberto':
        flash('Este inventário foi encerrado. A conferência está preservada.')
        return redirect(url_for('inventario_detalhe', inventario_id=inv.id))
    if request.method == 'POST':
        status = request.form.get('status', '')
        obs = texto_campo(request.form, 'observacao', 'Observações', 3000, erros)
        if campo and status not in ('Conferido', 'Divergência'):
            erros.append('Escolha Tudo correto ou Há divergência para o bem que você encontrou.')
        if status not in STATUS_INVENTARIO[1:]:
            erros.append('Selecione o resultado da conferência.')
        if request.form.get('revisao') != str(item.revisao):
            erros.append('A conferência mudou. Reabra este item.')
        if request.form.get('revisao_bem') != str(bem.revisao):
            erros.append('O bem foi atualizado enquanto você conferia. Reabra este item.')
        if status in ('Divergência', 'Não localizado') and len(obs) < 10:
            erros.append(
                'Descreva a divergência ou a busca realizada, com pelo menos 10 caracteres.'
            )
        if status == 'Conferido' and (
            bem.encerrado or str(bem.revisao) != item.retrato.get('revisao')
        ):
            erros.append(
                'O cadastro mudou desde a abertura do inventário. Registre a divergência e descreva a situação encontrada.'
            )
        if not erros:
            anterior_item = dict(
                status=item.status, observacao=item.observacao, conferente=item.conferente_nome
            )
            item.status = status
            item.observacao = obs
            item.conferente_id = g.usuario.id
            item.conferente_nome = g.usuario.nome
            item.conferido_em = datetime.now(timezone.utc)
            item.revisao += 1
            bem.conferido = status == 'Conferido' and not bem.encerrado
            db.session.add(
                EventoBem(
                    bem_id=bem.id,
                    usuario_id=g.usuario.id,
                    acao='Conferência de inventário',
                    detalhes=json.dumps(
                        dict(
                            inventario=inv.id,
                            antes=anterior_item,
                            depois=dict(status=status, observacao=obs, conferente=g.usuario.nome),
                        ),
                        ensure_ascii=False,
                    ),
                )
            )
            db.session.commit()
            flash('Conferência registrada.')
            if campo and request.form.get('continuar') == 'sim':
                return redirect(
                    url_for('inventario_campo', inventario_id=inv.id, local=campo_local, camera=1)
                )
            return redirect(
                url_for('inventario_detalhe', inventario_id=inv.id, **filtros_retorno_inventario())
            )
        db.session.rollback()
    return tela_operacao(
        'inventario',
        'inv_item_campo' if campo else 'inv_item',
        'Conferir bem',
        status=422 if erros else 200,
        inv=inv,
        item=item,
        ativo=bem,
        campo_local_filtro=campo_local,
        retorno_args=filtros_retorno_inventario(),
        erros=erros,
        valores=request.form if request.method == 'POST' else {},
    )


@app.post('/inventario/<int:inventario_id>/encerrar')
@login_obrigatorio
def encerrar_inventario(inventario_id):
    if g.usuario.perfil != 'Administrador':
        abort(403)
    inv = carregar(CampanhaInventario, inventario_id, True)
    divergentes = db.session.scalars(
        select(ItemInventario)
        .join(Bem)
        .where(
            ItemInventario.inventario_id == inv.id,
            ItemInventario.status == 'Conferido',
            or_(
                Bem.encerrado.is_(True),
                ItemInventario.retrato['revisao'].as_string() != cast(Bem.revisao, db.String),
            ),
        )
    ).all()
    if inv.status == 'Aberto' and divergentes:
        for item in divergentes:
            item.status = 'Divergência'
            item.observacao = (
                item.observacao
                + '\nCadastro alterado após a abertura / conferência. Requer revisão antes do encerramento.'
            ).strip()
            item.revisao += 1
            db.session.add(
                EventoBem(
                    bem_id=item.bem_id,
                    usuario_id=g.usuario.id,
                    acao='Revisão do inventário',
                    detalhes=json.dumps(
                        dict(inventario=inv.id, motivo='Cadastro alterado após a conferência'),
                        ensure_ascii=False,
                    ),
                )
            )
        db.session.commit()
        flash(
            'Itens alterados após a conferência foram destacados como divergência. Revise os resultados antes de encerrar novamente.'
        )
        return redirect(url_for('inventario_detalhe', inventario_id=inv.id, status='Divergência'))
    pendentes = (
        db.session.scalar(
            select(func.count())
            .select_from(ItemInventario)
            .where(ItemInventario.inventario_id == inv.id, ItemInventario.status == 'Pendente')
        )
        or 0
    )
    if inv.status != 'Aberto' or pendentes or request.form.get('confirmar') != 'sim':
        flash(
            'Para encerrar, trate todos os itens e confirme a conclusão. Divergências e não localizados permanecem no relatório.'
        )
    else:
        inv.status = 'Encerrado'
        inv.encerrado_em = datetime.now(timezone.utc)
        inv.encerrado_por = g.usuario.id
        db.session.commit()
        flash('Inventário encerrado. As conferências foram preservadas.')
    return redirect(url_for('inventario_detalhe', inventario_id=inv.id))


# Relatórios: filtros compartilhados pela tela e exportação, sem carregar fotos.
def consulta_relatorio():
    tipo = request.args.get('tipo', 'bens')
    if tipo not in ('bens', 'movimentacoes', 'baixas', 'inventario'):
        tipo = 'bens'
    q = request.args.get('q', '').strip()[:120]
    base_id = inteiro(request.args.get('base_id'))
    convenio_id = inteiro(request.args.get('convenio_id'))
    acervo = request.args.get('acervo', 'ativos')
    if acervo not in ('ativos', 'baixados', 'todos'):
        acervo = 'ativos'
    inicio = request.args.get('inicio', '')
    fim = request.args.get('fim', '')
    erros = []
    datas = {}
    for campo, valor in [('inicio', inicio), ('fim', fim)]:
        try:
            datas[campo] = date.fromisoformat(valor) if valor else None
        except ValueError:
            erros.append(f'Data de {campo} inválida.')
            datas[campo] = None
    if datas['inicio'] and datas['fim'] and datas['inicio'] > datas['fim']:
        erros.append('A data inicial deve ser anterior ou igual à final.')
    if tipo == 'bens':
        modelo = Bem
        consulta = select(Bem)
        col_data = Bem.data_aquisicao
        colunas = [
            'Bem',
            'Plaqueta',
            'Série',
            'Convênio',
            'Local',
            'Responsável',
            'Situação',
            'Aquisição',
            'Valor de aquisição (R$)',
            'Nota fiscal',
        ]
    elif tipo == 'movimentacoes':
        modelo = Movimento
        consulta = select(Movimento).join(Bem)
        col_data = Movimento.criado_em
        colunas = [
            'Movimento',
            'Bem',
            'Tipo',
            'Origem',
            'Destino',
            'Responsável no destino',
            'Situação',
            'Solicitado em',
            'Concluído em',
        ]
    elif tipo == 'baixas':
        modelo = ProcessoBaixa
        consulta = select(ProcessoBaixa).join(Bem)
        col_data = ProcessoBaixa.criado_em
        colunas = [
            'Processo de baixa',
            'Bem',
            'Motivo',
            'Processo administrativo',
            'Titular',
            'Destinação',
            'Situação',
            'Abertura',
            'Conclusão',
        ]
    else:
        modelo = ItemInventario
        consulta = select(ItemInventario).join(Bem)
        col_data = ItemInventario.conferido_em
        colunas = [
            'Inventário',
            'Bem',
            'Plaqueta',
            'Local na abertura',
            'Resultado',
            'Conferente',
            'Conferência',
            'Observações',
        ]
    # Local/convênio consideram o vínculo atual; origem histórica fica nas colunas.
    if base_id:
        consulta = consulta.where(Bem.base_id == base_id)
    if convenio_id:
        consulta = consulta.where(Bem.convenio_id == convenio_id)
    if tipo == 'bens' and acervo != 'todos':
        consulta = consulta.where(Bem.encerrado.is_(acervo == 'baixados'))
    if q:
        consulta = consulta.where(
            or_(
                Bem.nome.icontains(q, autoescape=True),
                Bem.serie.icontains(q, autoescape=True),
                Bem.numero_ngi.icontains(q, autoescape=True),
                Bem.plaqueta_original.icontains(q, autoescape=True),
            )
        )
    situacao = request.args.get('status', '')
    opcoes_status = {
        'bens': (),
        'movimentacoes': ('Pendente', 'Concluída', 'Cancelada'),
        'baixas': ('Em análise', 'Concluída', 'Indeferida', 'Cancelada'),
        'inventario': STATUS_INVENTARIO,
    }[tipo]
    if situacao not in opcoes_status:
        situacao = ''
    if situacao:
        consulta = consulta.where(modelo.status == situacao)
    inv_id = inteiro(request.args.get('inventario_id'))
    if tipo == 'inventario' and inv_id:
        consulta = consulta.where(ItemInventario.inventario_id == inv_id)
    if datas['inicio']:
        limite = (
            datas['inicio']
            if tipo == 'bens'
            else datetime.combine(
                datas['inicio'], datetime.min.time(), tzinfo=timezone(timedelta(hours=-3))
            ).astimezone(timezone.utc)
        )
        consulta = consulta.where(col_data >= limite)
    if datas['fim']:
        limite = datas['fim'] + timedelta(days=1)
        limite = (
            limite
            if tipo == 'bens'
            else datetime.combine(
                limite, datetime.min.time(), tzinfo=timezone(timedelta(hours=-3))
            ).astimezone(timezone.utc)
        )
        consulta = consulta.where(col_data < limite)
    if erros:
        consulta = consulta.where(False)
    return (
        consulta.order_by(modelo.id.desc()),
        dict(
            tipo=tipo,
            q=q,
            base_id=base_id,
            convenio_id=convenio_id,
            status=situacao,
            acervo=acervo,
            inicio=inicio,
            fim=fim,
            inventario_id=inv_id,
        ),
        colunas,
        erros,
    )


def linhas_relatorio(rows,tipo):
    for obj in rows:
        if tipo=='bens':
            yield [obj.nome,obj.patrimonio,obj.serie or obj.serie_excecao,obj.convenio,obj.local,obj.responsavel,
                'Baixado' if obj.encerrado else obj.situacao,datahora(obj.data_aquisicao),str(obj.valor).replace('.',',') if obj.valor is not None else 'Não informado',
                obj.nota_fiscal or ('Arquivo anexado' if obj.nota_fiscal_anexada else 'Não informada')]
        elif tipo=='movimentacoes':
            yield [f'MOV-{obj.id:06d}',obj.origem.get('nome',''),obj.tipo,obj.origem.get('local',''),obj.destino.get('local',''),
                obj.destino.get('responsavel',''),obj.status,datahora(obj.criado_em),datahora(obj.concluido_em)]
        elif tipo=='baixas':
            yield [f'BAI-{obj.id:06d}',obj.retrato.get('nome',''),obj.motivo,obj.processo,obj.titularidade,obj.destinacao,obj.status,datahora(obj.criado_em),datahora(obj.concluido_em)]
        else:
            r=obj.retrato
            yield [f'INV-{obj.inventario_id:06d}',r.get('nome',''),r.get('numero_ngi') or r.get('plaqueta_original') or '',r.get('local',''),obj.status,obj.conferente_nome,datahora(obj.conferido_em),obj.observacao]


@app.get('/relatorios/operacoes')
@login_obrigatorio
def relatorio_operacional():
    consulta,filtros,colunas,erros=consulta_relatorio()
    pagina=paginar_operacao(consulta)
    # Fonte única de filtros para a visualização e o CSV.
    link_csv=url_for('exportar_relatorio',**{k:v for k,v in filtros.items() if v not in (None,'')})
    return tela_operacao('relatorios','relatorios','Relatórios',status=422 if erros else 200,filtros=filtros,colunas=colunas,erros=erros,
        linhas=list(linhas_relatorio(pagina['rows'],filtros['tipo'])),link_csv=link_csv,
        bases_relatorio=db.session.scalars(select(BaseLocal).order_by(BaseLocal.nome)).all(),
        convenios_relatorio=db.session.scalars(select(Convenio).order_by(Convenio.nome)).all(),**pagina)


@app.get('/relatorios/exportar.csv')
@login_obrigatorio
def exportar_relatorio():
    consulta, filtros, colunas, erros = consulta_relatorio()
    if erros:
        return Response(' '.join(erros), status=422, mimetype='text/plain')

    def seguro(valor):
        valor = str(valor if valor is not None else '')
        if valor.lstrip().startswith(('=', '+', '-', '@')) or valor.startswith(('\t', '\r', '\n')):
            valor = "'" + valor
        return valor

    @stream_with_context
    def gerar():
        yield '\ufeff'
        out = io.StringIO()
        escritor = csv.writer(out, delimiter=';', lineterminator='\r\n')
        escritor.writerow(colunas)
        yield out.getvalue()
        out.seek(0)
        out.truncate(0)
        registros = db.session.scalars(consulta.execution_options(yield_per=200))
        for linha in linhas_relatorio(registros, filtros['tipo']):
            escritor.writerow([seguro(v) for v in linha])
            yield out.getvalue()
            out.seek(0)
            out.truncate(0)

    return Response(
        gerar(),
        content_type='text/csv; charset=utf-8',
        headers={
            'Content-Disposition': f'attachment; filename=relatorio_{filtros["tipo"]}_{hoje_local()}.csv'
        },
    )


NOVAS_TELAS_V10={
'enc_tabs':r'''<nav class="registry-navigation" aria-label="Encerramento e baixa"><a href="{{ url_for('encerramento_convenios') }}" class="{{ 'current' if request.endpoint!='baixas' }}">Encerramento de convênios</a>{% if pode_acessar('baixas') %}<a href="{{ url_for('baixas') }}" class="{{ 'current' if request.endpoint=='baixas' }}">Processos de baixa</a>{% endif %}</nav>''',
'enc_lista':r'''<div class="list-heading"><div><h1>Encerramento de convênios</h1><p>Acompanhe os bens de cada convênio e registre sua destinação documental.</p></div></div>{% include 'enc_tabs' %}<section class="panel"><form method="get" class="registry-toolbar"><div class="field"><label for="enc-q">Pesquisar convênio</label><input id="enc-q" name="q" maxlength="120" value="{{ q }}"></div><button class="btn primary">Pesquisar</button></form><div class="tablewrap"><table><thead><tr><th>Convênio</th><th>Fim da vigência</th><th>Bens vinculados</th><th>Sem destinação registrada</th><th></th></tr></thead><tbody>{% for c in rows %}<tr><td><strong>{{ c.nome }}</strong><small class="table-sub">{{ c.numero }}</small></td><td>{{ c.fim|datahora }}{% if c.fim and c.fim<hoje_enc %}<small class="table-sub">Vigência encerrada</small>{% endif %}</td><td>{{ contagens.get(c.id,0) }}</td><td>{{ contagens.get(c.id,0)-definidos.get(c.id,0) }}</td><td><a class="text-action" href="{{ url_for('encerramento_detalhe',convenio_id=c.id) }}">Acompanhar bens</a></td></tr>{% else %}<tr><td colspan="5" class="list-empty">Nenhum convênio encontrado.</td></tr>{% endfor %}</tbody></table></div>{% include 'op_paginacao' %}</section>''',
'enc_detalhe':r'''<a class="back" href="{{ url_for('encerramento_convenios') }}">← Encerramento de convênios</a><div class="list-heading"><div><h1>{{ convenio.nome }}</h1><p>Vigência final: {{ convenio.fim|datahora }} · {{ total_enc }} bens vinculados</p></div>{% if pode_acessar('relatorio_final_pdf') %}<div class="enc-relatorio-acoes"><a class="btn primary" href="{{ url_for('relatorio_final_pdf',convenio_id=convenio.id) }}" target="_blank" rel="noopener">Relatório final (PDF)</a><a class="btn" href="{{ url_for('relatorio_final_xlsx',convenio_id=convenio.id) }}">Relatório final (Excel)</a></div>{% endif %}</div><div class="op-metrics"><article><span>Bens vinculados</span><strong>{{ total_enc }}</strong></article><article><span>Destinação registrada</span><strong>{{ definidos_enc }}</strong></article><article><span>A definir</span><strong>{{ total_enc-definidos_enc }}</strong></article></div><section class="panel"><p class="hint">Este acompanhamento organiza a destinação prevista no instrumento e no processo competente. O registro não transfere propriedade nem dá baixa automaticamente.</p><form method="get" class="registry-toolbar"><div class="field"><label for="enc-busca">Pesquisar bem</label><input id="enc-busca" name="q" maxlength="120" value="{{ q }}" placeholder="Nome, série ou nº de patrimônio"></div><button class="btn primary">Pesquisar</button></form><div class="tablewrap"><table><thead><tr><th>Bem / identificação</th><th>Local</th><th>Responsável</th><th>Destinação registrada</th><th></th></tr></thead><tbody>{% for b in rows %}{% set d=destinos.get(b.id) %}<tr><td><a class="asset-name" href="{{ url_for('ficha',bem_id=b.id,consulta=1) }}">{{ b.nome }}</a><small class="table-sub">{{ b.patrimonio }}{% if b.encerrado %} · Baixado{% endif %}</small></td><td>{{ b.local }}</td><td>{{ b.responsavel }}</td><td>{{ d.destino if d else 'Não definida' }}{% if d %}<small class="table-sub">{{ d.referencia }}</small>{% endif %}</td><td>{% if not usuario.leitura %}<a class="text-action" href="{{ url_for('definir_destinacao',convenio_id=convenio.id,bem_id=b.id) }}">{{ 'Revisar destino' if d else 'Registrar destino' }}</a>{% endif %}</td></tr>{% else %}<tr><td colspan="5" class="list-empty">Nenhum bem vinculado encontrado.</td></tr>{% endfor %}</tbody></table></div>{% include 'op_paginacao' %}</section>''',
'enc_form':r'''<a class="back" href="{{ url_for('encerramento_detalhe',convenio_id=convenio.id) }}">← Bens do convênio</a><div class="list-heading"><div><h1>Registrar destinação</h1><p>{{ ativo.nome }} · {{ convenio.nome }}</p></div></div>{% include 'op_erros' %}<section class="form-section registry-form"><h2>Destinação documental do bem</h2><form method="post"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><input type="hidden" name="revisao" value="{{ destino.revisao if destino else 0 }}"><div class="fields"><div class="field wide"><label for="destino-enc">Destinação *</label><select id="destino-enc" name="destino">{% for opcao in opcoes_destino %}<option {{ 'selected' if valores.get('destino')==opcao }}>{{ opcao }}</option>{% endfor %}</select></div><div class="field wide"><label for="destino-ref">Instrumento / processo / decisão *</label><input id="destino-ref" name="referencia" maxlength="300" required value="{{ valores.get('referencia','') }}"></div><div class="field wide"><label for="destino-just">Justificativa *</label><textarea id="destino-just" name="justificativa" required minlength="10" maxlength="3000">{{ valores.get('justificativa','') }}</textarea></div></div><div class="dialog-actions"><a class="btn" href="{{ url_for('encerramento_detalhe',convenio_id=convenio.id) }}">Cancelar</a><button class="btn primary">Salvar destinação</button></div></form></section>''',
'inv_scanner':r'''
<dialog class="inventory-camera-dialog" id="inventory-camera"><div class="section-top"><h2>Ler QR Code</h2><button type="button" class="btn" id="inventory-camera-close">Fechar</button></div><video id="inventory-video" playsinline muted></video><p id="inventory-camera-status" role="status">Aponte para o QR Code da plaqueta.</p></dialog>
<script>
document.addEventListener('DOMContentLoaded',()=>{const dialog=document.querySelector('#inventory-camera'),video=document.querySelector('#inventory-video'),status=document.querySelector('#inventory-camera-status');let stream,running=false,timer,starting=false;
function stop(){running=false;clearTimeout(timer);if(stream)stream.getTracks().forEach(t=>t.stop());stream=null;video.srcObject=null;}
function result(text){stop();const url=new URL({{ url_for('inventario_localizar',inventario_id=inv.id)|tojson }},location.origin);url.searchParams.set('codigo',text);location.assign(url.pathname+url.search);}
async function start(){if(starting)return;starting=true;dialog.showModal();status.textContent='Abrindo a câmera…';try{if(!window.BarcodeDetector||!navigator.mediaDevices?.getUserMedia)throw new Error('A leitura direta não está disponível neste navegador. Use a busca por nome, série ou patrimônio; você também pode ler o QR pela câmera do celular e abrir a ficha.');const formats=await BarcodeDetector.getSupportedFormats();if(!formats.includes('qr_code'))throw new Error('Leitura não disponível. Use a busca por nome, série ou patrimônio.');const detector=new BarcodeDetector({formats:['qr_code']});stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'}},audio:false});if(!dialog.open){stop();return;}video.srcObject=stream;await video.play();running=true;status.textContent='Aponte para o QR Code da plaqueta.';async function scan(){if(!running)return;try{const found=await detector.detect(video);if(found[0]?.rawValue){result(found[0].rawValue);return;}}catch(e){}if(running)timer=setTimeout(scan,250);}scan();}catch(e){stop();status.textContent=e.name==='NotAllowedError'?'Permissão de câmera negada. Libere a câmera ou use a busca por nome, série ou patrimônio.':e.message||'Não foi possível abrir a câmera.';}finally{starting=false;}}
document.querySelectorAll('[data-inventory-scan]').forEach(b=>b.addEventListener('click',start));document.querySelector('#inventory-camera-close').addEventListener('click',()=>{stop();dialog.close();});dialog.addEventListener('close',stop);dialog.addEventListener('cancel',stop);window.addEventListener('pagehide',stop);document.addEventListener('visibilitychange',()=>{if(document.hidden){stop();if(dialog.open)dialog.close();}});
});
</script>'''
}

ETIQUETA_V10 = r'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Plaqueta · {{ bem.nome }}</title><style>
*{box-sizing:border-box}body{font:14px system-ui;margin:0;padding:30px;background:#f3f6f2;color:#173f30}.toolbar{max-width:900px;margin:auto}h1{font-size:24px}p{line-height:1.7;color:#637568}button,.toolbar a{display:inline-block;border:1px solid #bacebe;border-radius:7px;padding:12px 18px;background:white;color:#174c37;text-decoration:none;font:600 13px system-ui;cursor:pointer;margin:5px}button{background:#174c37;color:#fff}.sheet{width:190mm;min-height:80mm;padding:10mm;margin:24px auto;background:white;border:1px solid #dce4dd}.label{width:40mm;height:25mm;border:.25mm solid #333;border-radius:1mm;display:flex;align-items:center;padding:1mm;background:#fff;color:#000;overflow:hidden}.label img{width:20mm;height:20mm;flex-shrink:0;image-rendering:pixelated}.label-text{width:17mm;min-width:0;display:flex;flex-direction:column;gap:1.2mm;padding-left:.5mm;overflow-wrap:anywhere}.label-text small{font-size:5.5pt;font-weight:700;line-height:1.2}.label-text strong{font-family:monospace;font-size:7pt;line-height:1.25}.label-text span{font-size:5pt;line-height:1.2}.missing{padding:24px;border:1px dashed #bacfbe;border-radius:8px}.sheet[hidden]{display:none}@media(max-width:800px){body{padding:18px}.sheet{width:100%;min-height:180px;padding:20px}}@media print{@page{size:A4;margin:10mm}body{background:white;margin:0;padding:0}.toolbar{display:none!important}.sheet{width:auto;min-height:0;padding:0;margin:0;border:0}.label{break-inside:avoid}}
</style></head><body><div class="toolbar"><a href="{{ url_for('ficha',bem_id=bem.id,consulta=1) }}">← Voltar ao bem</a><h1>Plaqueta patrimonial</h1><p>{{ bem.nome }} · {{ bem.patrimonio }}</p>{% if identificado %}<p>Dimensão: <strong>40 × 25 mm</strong>. Na impressão, use escala <strong>100% / tamanho real</strong> e desative cabeçalhos e rodapés. Confira a medida e a leitura do QR em uma impressão de teste.</p><button type="button" onclick="window.print()">Imprimir / salvar PDF</button>{% else %}<div class="missing">Este bem ainda não tem número. Volte à ficha para gerar o número de patrimônio ou cadastrar a plaqueta antiga.</div>{% endif %}</div>{% if identificado %}<div class="sheet"><div class="label"><img src="{{ url_for('qr_bem',bem_id=bem.id) }}" alt="QR Code"><div class="label-text"><small>NGI ICMBio Carajás · Patrimônio</small><strong>{{ bem.numero_ngi or bem.plaqueta_original }}</strong>{% if bem.plaqueta_original %}<span>Plaqueta antiga: {{ bem.plaqueta_original }}</span>{% endif %}</div></div></div>{% endif %}</body></html>'''
app.jinja_loader=ChoiceLoader([DictLoader(NOVAS_TELAS_V10),app.jinja_loader])
# A etiqueta contém um endereço da ficha, sem dados pessoais no QR Code.
PUBLIC_URL=os.environ.get('PUBLIC_URL','https://patrimonio-ngi-carajas.onrender.com').rstrip('/')
if not PUBLIC_URL.startswith('https://') or any(c in PUBLIC_URL for c in ('\r','\n','?','#')):
    raise RuntimeError('PUBLIC_URL deve ser a URL HTTPS pública do sistema, sem caminho de consulta.')


@app.get('/bem/<int:bem_id>/qr.png')
@login_obrigatorio
def qr_bem(bem_id):
    carregar(Bem, bem_id)
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    qr.add_data(PUBLIC_URL + url_for('ficha', bem_id=bem_id))
    qr.make(fit=True)
    out = io.BytesIO()
    qr.make_image(fill_color='black', back_color='white').save(out, format='PNG')
    return Response(out.getvalue(), mimetype='image/png')


@app.get('/bem/<int:bem_id>/plaqueta')
@login_obrigatorio
def imprimir_plaqueta(bem_id):
    bem=carregar(Bem,bem_id)
    if not (bem.numero_ngi or bem.plaqueta_original):
        flash('Este bem ainda não tem identificação. Gere o número na ficha antes de imprimir.')
        return redirect(url_for('ficha',bem_id=bem.id))
    return redirect(url_for('plaqueta_pdf_individual',bem_id=bem.id))


@app.get('/inventario/<int:inventario_id>/localizar')
@login_obrigatorio
def inventario_localizar(inventario_id):
    return redirect(url_for('inventario_campo',inventario_id=inventario_id,
        codigo=request.args.get('codigo','').strip()[:500],local=request.args.get('local','').strip()[:160]))


@app.get('/encerramento')
@login_obrigatorio
def encerramento_convenios():
    q=request.args.get('q','').strip()[:120]
    consulta=select(Convenio).where(Convenio.nome_chave!=NOME_PATRIMONIO_UNIAO.casefold())
    if convenios_do_gestor() is not None:consulta=consulta.where(Convenio.id.in_(sorted(convenios_do_gestor()) or [-1]))
    if q:consulta=consulta.where(Convenio.nome.icontains(q,autoescape=True))
    pag=paginar_operacao(consulta.order_by(Convenio.fim.asc().nullslast(),Convenio.id))
    ids=[c.id for c in pag['rows']]
    contagens=dict(db.session.execute(select(Bem.convenio_id,func.count()).where(Bem.convenio_id.in_(ids)).group_by(Bem.convenio_id)).all()) if ids else {}
    definidos=dict(db.session.execute(select(DestinacaoConvenio.convenio_id,func.count()).join(Bem,DestinacaoConvenio.bem_id==Bem.id).where(DestinacaoConvenio.convenio_id.in_(ids),Bem.convenio_id==DestinacaoConvenio.convenio_id).group_by(DestinacaoConvenio.convenio_id)).all()) if ids else {}
    return tela_operacao('baixas','enc_lista','Encerramento de convênios',q=q,contagens=contagens,definidos=definidos,hoje_enc=hoje_local(),**pag)


@app.get('/encerramento/<int:convenio_id>')
@login_obrigatorio
def encerramento_detalhe(convenio_id):
    if not convenio_visivel(convenio_id):
        abort(404)
    convenio=carregar(Convenio,convenio_id)
    q=request.args.get('q','').strip()[:120]
    consulta=select(Bem).where(Bem.convenio_id==convenio_id)
    if q:consulta=consulta.where(or_(Bem.nome.icontains(q,autoescape=True),Bem.serie.icontains(q,autoescape=True),Bem.numero_ngi.icontains(q,autoescape=True)))
    pag=paginar_operacao(consulta.order_by(Bem.nome,Bem.id))
    ids=[b.id for b in pag['rows']]
    destinos={d.bem_id:d for d in db.session.scalars(select(DestinacaoConvenio).where(DestinacaoConvenio.convenio_id==convenio_id,DestinacaoConvenio.bem_id.in_(ids))).all()} if ids else {}
    total=db.session.scalar(select(func.count()).select_from(Bem).where(Bem.convenio_id==convenio_id)) or 0
    definidos=db.session.scalar(select(func.count()).select_from(DestinacaoConvenio).join(Bem,DestinacaoConvenio.bem_id==Bem.id).where(DestinacaoConvenio.convenio_id==convenio_id,Bem.convenio_id==convenio_id)) or 0
    return tela_operacao('baixas','enc_detalhe','Destinação dos bens',convenio=convenio,q=q,destinos=destinos,total_enc=total,definidos_enc=definidos,**pag)


@app.route('/encerramento/<int:convenio_id>/bem/<int:bem_id>', methods=['GET', 'POST'])
@login_obrigatorio
def definir_destinacao(convenio_id, bem_id):
    if g.usuario.leitura:
        abort(403)
    convenio = carregar(Convenio, convenio_id)
    bem = carregar(Bem, bem_id, request.method == 'POST')
    if bem.convenio_id != convenio_id:
        abort(404)
    destino = db.session.scalar(
        select(DestinacaoConvenio)
        .where(DestinacaoConvenio.convenio_id == convenio_id, DestinacaoConvenio.bem_id == bem_id)
        .with_for_update()
    )
    opcoes = (
        'Permanência com o titular',
        'Devolução ao proprietário',
        'Transferência a definir no processo',
        'Doação a definir no processo',
        'Outra destinação documentada',
    )
    erros = []
    if request.method == 'POST':
        escolha = request.form.get('destino', '')
        if escolha not in opcoes:
            erros.append('Selecione uma destinação válida.')
        justificativa = texto_campo(request.form, 'justificativa', 'Justificativa', 3000, erros, 10)
        referencia = texto_campo(
            request.form, 'referencia', 'Instrumento / processo / decisão', 300, erros, 3
        )
        if request.form.get('revisao') != str(destino.revisao if destino else 0):
            erros.append('A destinação foi alterada. Reabra esta tela antes de salvar.')
        if not erros:
            antes = (
                dict(
                    destino=destino.destino,
                    justificativa=destino.justificativa,
                    referencia=destino.referencia,
                )
                if destino
                else None
            )
            if destino is None:
                destino = DestinacaoConvenio(convenio_id=convenio_id, bem_id=bem_id, revisao=0)
                db.session.add(destino)
            destino.destino = escolha
            destino.justificativa = justificativa
            destino.referencia = referencia
            destino.autor_id = g.usuario.id
            destino.autor_nome = g.usuario.nome
            destino.revisao += 1
            destino.atualizado_em = datetime.now(timezone.utc)
            db.session.add(
                EventoBem(
                    bem_id=bem.id,
                    usuario_id=g.usuario.id,
                    acao='Destinação no convênio',
                    detalhes=json.dumps(
                        dict(
                            antes=antes,
                            depois=dict(
                                destino=escolha, referencia=referencia, justificativa=justificativa
                            ),
                        ),
                        ensure_ascii=False,
                    ),
                )
            )
            db.session.commit()
            flash(
                'Destinação registrada para acompanhamento. Isso não confirma transferência, doação nem baixa do bem.'
            )
            return redirect(url_for('encerramento_detalhe', convenio_id=convenio_id))
        db.session.rollback()
    valores = (
        request.form
        if request.method == 'POST'
        else dict(
            destino=destino.destino if destino else '',
            justificativa=destino.justificativa if destino else '',
            referencia=destino.referencia if destino else '',
        )
    )
    return tela_operacao(
        'baixas',
        'enc_form',
        'Registrar destinação',
        status=422 if erros else 200,
        convenio=convenio,
        ativo=bem,
        destino=destino,
        opcoes_destino=opcoes,
        valores=valores,
        erros=erros,
    )


# ============================================================
# RELATÓRIO FINAL DO CONVÊNIO (PDF e Excel)
# Consolida bens, notas fiscais, situação, inventários, termos e pendências.
# Não exibe dados financeiros do instrumento (número, financiador, gestor, valor).
# ============================================================
from xml.sax.saxutils import escape as xml_escape
import zipfile
from reportlab.lib import colors as rl_cores
from reportlab.lib.pagesizes import landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle, KeepTogether, PageBreak)

COR_VERDE = rl_cores.HexColor('#0E3B2B')
COR_VERDE_MEDIO = rl_cores.HexColor('#174C37')
COR_CLARO = rl_cores.HexColor('#EEF5F0')
COR_LINHA = rl_cores.HexColor('#D5E2D9')
COR_TEXTO = rl_cores.HexColor('#1F2D26')
COR_SUAVE = rl_cores.HexColor('#55695D')
COR_ALERTA = rl_cores.HexColor('#8A4B00')
COR_ALERTA_FUNDO = rl_cores.HexColor('#FFF4DE')
COR_LIMA = rl_cores.HexColor('#C6F36B')


def data_br(valor, com_hora=False):
    if not valor:
        return ''
    if isinstance(valor, datetime):
        valor = utc(valor).astimezone(timezone(timedelta(hours=-3)))
        return valor.strftime('%d/%m/%Y %H:%M' if com_hora else '%d/%m/%Y')
    return valor.strftime('%d/%m/%Y')


def data_local(valor):
    if isinstance(valor, datetime):
        return utc(valor).astimezone(timezone(timedelta(hours=-3))).date()
    return valor


def dados_relatorio_final(convenio):
    """Reúne, numa única leitura, tudo o que o relatório final mostra."""
    agora = datetime.now(timezone.utc)
    bens = db.session.scalars(select(Bem).where(Bem.convenio_id == convenio.id)
                              .order_by(Bem.encerrado, Bem.local, Bem.nome, Bem.id)).all()
    ids = [b.id for b in bens]
    destinos = {d.bem_id: d for d in db.session.scalars(select(DestinacaoConvenio).where(
        DestinacaoConvenio.convenio_id == convenio.id, DestinacaoConvenio.bem_id.in_(ids)))} if ids else {}
    com_arquivo = set(db.session.scalars(select(NotaFiscalBem.bem_id).where(NotaFiscalBem.bem_id.in_(ids)))) if ids else set()

    ultima, campanhas = {}, {}
    if ids:
        consulta = (select(ItemInventario, CampanhaInventario)
                    .join(CampanhaInventario, CampanhaInventario.id == ItemInventario.inventario_id)
                    .where(ItemInventario.bem_id.in_(ids)).order_by(ItemInventario.id))
        for item, camp in db.session.execute(consulta):
            c = campanhas.setdefault(camp.id, dict(campanha=camp, cont={}))
            c['cont'][item.status] = c['cont'].get(item.status, 0) + 1
            if item.status != 'Pendente' and item.conferido_em:
                quando = utc(item.conferido_em)
                if item.bem_id not in ultima or quando > ultima[item.bem_id]['data']:
                    ultima[item.bem_id] = dict(status=item.status, data=quando, campanha=camp.id)

    docs = db.session.scalars(select(Documento).where(documentos_do_bem(ids), Documento.tipo.in_(TIPOS_ACEITE))
                              .order_by(Documento.id)).all() if ids else []
    kit = {}
    if docs:
        for documento_id, bem_id in db.session.execute(select(TermoBem.documento_id, TermoBem.bem_id)
                .where(TermoBem.documento_id.in_([d.id for d in docs])).order_by(TermoBem.bem_id)):
            kit.setdefault(documento_id, []).append(bem_id)
    aceite_doc = {}
    if docs:
        for a in db.session.scalars(select(AceiteTermo).where(AceiteTermo.documento_id.in_([d.id for d in docs])).order_by(AceiteTermo.id)):
            atual = aceite_doc.get(a.documento_id)
            if atual is None or atual.status != 'Aceito':
                aceite_doc[a.documento_id] = a
    termo_bem = {}
    termos = []
    nomes_bens = {b.id: b for b in bens}
    for d in docs:
        cobertos = [x for x in dict.fromkeys(([d.bem_id] if d.bem_id else []) + kit.get(d.id, [])) if x in nomes_bens]
        for bem_id in cobertos:
            termo_bem[bem_id] = d
        a = aceite_doc.get(d.id)
        if a and a.status == 'Aceito':
            aceite_txt = 'Aceito em ' + data_br(a.respondido_em, True) + ' por ' + a.nome_digitado
        elif a and a.situacao == 'Pendente':
            aceite_txt = 'Aguardando aceite de ' + a.email
        elif a and a.status == 'Recusado':
            aceite_txt = 'Recusado em ' + data_br(a.respondido_em)
        else:
            aceite_txt = 'Sem aceite eletrônico (assinatura em papel)'
        cob = [nomes_bens[x] for x in cobertos]
        termos.append(dict(numero='DOC-%06d' % d.id, tipo=d.tipo, emissao=data_local(d.criado_em),
                           bem='; '.join(b.nome for b in cob),
                           patrimonio='; '.join(b.numero_ngi or b.plaqueta_original or 'Sem plaqueta' for b in cob),
                           responsavel=nome_sugerido_aceite(d), emitente=d.autor_nome, aceite=aceite_txt,
                           aceito=bool(a and a.status == 'Aceito')))

    linhas = []
    pend = {k: [] for k in ('nao_localizado', 'divergencia', 'sem_conferencia', 'sem_nf', 'sem_termo', 'sem_aceite', 'sem_destinacao')}
    resumo = dict(total=len(bens), ativos=0, baixados=0, nao_localizados=0, divergencias=0, conferidos=0, nunca=0,
                  com_nf=0, com_termo=0, com_aceite=0, com_destinacao=0, valor=Decimal('0'), sem_valor=0)
    for n, b in enumerate(bens, 1):
        patrimonio = b.numero_ngi or b.plaqueta_original or 'Sem plaqueta'
        u = ultima.get(b.id)
        d = destinos.get(b.id)
        doc = termo_bem.get(b.id)
        nf = b.nota_fiscal or ('Arquivo anexado' if b.id in com_arquivo else '')
        a = aceite_doc.get(doc.id) if doc else None
        if b.encerrado:
            resumo['baixados'] += 1
            situacao = 'Baixado em ' + data_br(b.encerrado_em) if b.encerrado_em else 'Baixado'
        else:
            resumo['ativos'] += 1
            situacao = 'Ativo · ' + (b.situacao or '')
        if b.valor is not None:
            resumo['valor'] += b.valor
        else:
            resumo['sem_valor'] += 1
        if nf:
            resumo['com_nf'] += 1
        if doc:
            resumo['com_termo'] += 1
        if a and a.status == 'Aceito':
            resumo['com_aceite'] += 1
        if d:
            resumo['com_destinacao'] += 1
        if u:
            resumo['conferidos'] += 1
        else:
            resumo['nunca'] += 1
        conf = (u['status'] + ' em ' + data_br(u['data'])) if u else 'Nunca conferido'
        termo_txt = ('%s · %s' % ('DOC-%06d' % doc.id, 'aceito' if a and a.status == 'Aceito' else 'sem aceite')) if doc else 'Sem termo'
        linha = dict(n=n, id=b.id, patrimonio=patrimonio, nome=b.nome, marca=b.marca or '', modelo=b.modelo or '',
                     serie=b.serie or '', categoria=b.categoria or '', nf=nf, fornecedor=b.fornecedor or '',
                     data_aquisicao=b.data_aquisicao, valor=b.valor, local=b.local or '', complemento=b.complemento or '',
                     responsavel=b.responsavel or '', situacao=situacao, conservacao=b.conservacao or '',
                     ultima_conferencia=conf, ultima_data=data_local(u['data']) if u else None,
                     ultimo_resultado=u['status'] if u else 'Nunca conferido',
                     termo=termo_txt, destinacao=d.destino if d else 'A definir',
                     referencia=d.referencia if d else '', ativo=not b.encerrado)
        linhas.append(linha)
        if not b.encerrado:
            if u and u['status'] == 'Não localizado':
                resumo['nao_localizados'] += 1
                pend['nao_localizado'].append(linha)
            if u and u['status'] == 'Divergência':
                resumo['divergencias'] += 1
                pend['divergencia'].append(linha)
            if not u or (agora - u['data']).days > 365:
                pend['sem_conferencia'].append(linha)
            if not nf:
                pend['sem_nf'].append(linha)
            if not doc:
                pend['sem_termo'].append(linha)
            elif not (a and a.status == 'Aceito'):
                pend['sem_aceite'].append(linha)
            if not d:
                pend['sem_destinacao'].append(linha)

    inventarios = []
    for c in sorted(campanhas.values(), key=lambda x: x['campanha'].id):
        camp, cont = c['campanha'], c['cont']
        total = sum(cont.values())
        inventarios.append(dict(numero='INV-%06d' % camp.id, nome=camp.nome, local=camp.local, status=camp.status,
            abertura=data_local(camp.criado_em), prazo=camp.prazo, encerramento=data_local(camp.encerrado_em),
            comissao=camp.comissao or '', total=total, conferidos=cont.get('Conferido', 0),
            divergencias=cont.get('Divergência', 0), nao_localizados=cont.get('Não localizado', 0),
            pendentes=cont.get('Pendente', 0), acuracia=pct(cont.get('Conferido', 0), total)))

    emitido = datetime.now(timezone.utc)
    base_hash = json.dumps(dict(convenio=convenio.id, nome=convenio.nome, emitido=emitido.isoformat(),
        bens=[[l['id'], l['patrimonio'], l['situacao'], l['ultima_conferencia'], l['termo'], l['destinacao'], l['nf']] for l in linhas]),
        ensure_ascii=False, sort_keys=True)
    integridade = hashlib.sha256(base_hash.encode()).hexdigest()
    return dict(convenio=convenio, linhas=linhas, resumo=resumo, inventarios=inventarios, termos=termos,
                pendencias=pend, emitido=emitido, emitido_por=g.usuario.nome, integridade=integridade,
                codigo='-'.join(integridade[i:i + 4].upper() for i in (0, 4, 8)))


TITULOS_PENDENCIAS = [
    ('nao_localizado', 'Não localizados no último inventário', 'Apurar o paradeiro antes de encerrar. Não dar baixa sem apuração.'),
    ('divergencia', 'Com divergência no último inventário', 'Atualizar local, responsável ou estado no cadastro e refazer o termo.'),
    ('sem_conferencia', 'Nunca conferidos ou sem conferência há mais de 1 ano', 'Incluir no próximo inventário.'),
    ('sem_nf', 'Sem nota fiscal informada', 'Registrar o número ou anexar a nota, quando existir.'),
    ('sem_termo', 'Sem termo de responsabilidade', 'Emitir o termo e enviar para aceite.'),
    ('sem_aceite', 'Termo emitido, sem aceite eletrônico', 'Confirmar o aceite ou anexar o termo assinado em papel.'),
    ('sem_destinacao', 'Sem destinação definida para o encerramento', 'Registrar a destinação em Encerramento e baixa.'),
]


def nome_arquivo_relatorio(convenio, extensao):
    base = re.sub(r'[^A-Za-z0-9]+', '-', unicodedata.normalize('NFKD', convenio.nome).encode('ascii', 'ignore').decode()).strip('-').lower() or 'convenio'
    return f'relatorio-final-{base}-{hoje_local().isoformat()}.{extensao}'


# ---------- PDF ----------
def _estilos_pdf():
    base = dict(fontName='NGI', textColor=COR_TEXTO, leading=11, fontSize=8.5)
    return dict(
        titulo=ParagraphStyle('titulo', fontName='NGI-Bold', fontSize=22, leading=27, textColor=COR_VERDE),
        convenio=ParagraphStyle('convenio', fontName='NGI-Bold', fontSize=15, leading=19, textColor=COR_VERDE_MEDIO),
        sub=ParagraphStyle('sub', fontName='NGI', fontSize=9.5, leading=14, textColor=COR_SUAVE),
        h2=ParagraphStyle('h2', fontName='NGI-Bold', fontSize=13, leading=17, textColor=COR_VERDE, spaceBefore=6, spaceAfter=4),
        txt=ParagraphStyle('txt', fontName='NGI', fontSize=9, leading=13, textColor=COR_TEXTO),
        nota=ParagraphStyle('nota', fontName='NGI', fontSize=8, leading=11.5, textColor=COR_SUAVE),
        cel=ParagraphStyle('cel', **base),
        celp=ParagraphStyle('celp', fontName='NGI', fontSize=7.3, leading=9.2, textColor=COR_TEXTO),
        celb=ParagraphStyle('celb', fontName='NGI-Bold', fontSize=7.5, leading=9.4, textColor=COR_TEXTO),
        cab=ParagraphStyle('cab', fontName='NGI-Bold', fontSize=7.4, leading=9.2, textColor=rl_cores.white),
        kpi=ParagraphStyle('kpi', fontName='NGI-Bold', fontSize=20, leading=23, textColor=COR_VERDE),
        kpil=ParagraphStyle('kpil', fontName='NGI-Bold', fontSize=8, leading=10, textColor=COR_TEXTO),
        kpis=ParagraphStyle('kpis', fontName='NGI', fontSize=7.2, leading=9.2, textColor=COR_SUAVE),
        bullet=ParagraphStyle('bullet', fontName='NGI', fontSize=8.6, leading=12.5, textColor=COR_TEXTO, leftIndent=10, bulletIndent=0),
    )


def _p(texto, estilo):
    return Paragraph(xml_escape(str(texto if texto is not None else '')).replace('\n', '<br/>'), estilo)


def _tabela(dados, larguras, cabecalho=True, zebra=True):
    t = Table(dados, colWidths=larguras, repeatRows=1 if cabecalho else 0)
    estilo = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4),
              ('TOPPADDING', (0, 0), (-1, -1), 3.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
              ('LINEBELOW', (0, 0), (-1, -1), 0.4, COR_LINHA)]
    if cabecalho:
        estilo += [('BACKGROUND', (0, 0), (-1, 0), COR_VERDE), ('VALIGN', (0, 0), (-1, 0), 'MIDDLE')]
    if zebra:
        for i in range(1 if cabecalho else 0, len(dados)):
            if i % 2 == 0:
                estilo.append(('BACKGROUND', (0, i), (-1, i), rl_cores.HexColor('#F6F9F7')))
    t.setStyle(TableStyle(estilo))
    return t


class _CanvasNumerado(pdf_canvas.Canvas):
    # Duas passagens: só no fim se sabe o total de páginas ("Página 2 de 5").
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._paginas = []

    def showPage(self):
        self._paginas.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._paginas)
        for estado in self._paginas:
            self.__dict__.update(estado)
            self.setFont('NGI', 7.2)
            self.setFillColor(COR_SUAVE)
            self.drawRightString(self._pagesize[0] - 14 * mm, 8 * mm, f'Página {self._pageNumber} de {total}')
            super().showPage()
        super().save()


def gerar_pdf_relatorio_final(dados):
    E = _estilos_pdf()
    convenio, r = dados['convenio'], dados['resumo']
    pagina = landscape(A4)
    margem = 14 * mm
    largura = pagina[0] - 2 * margem
    saida = io.BytesIO()
    emitido_txt = data_br(dados['emitido'], True)
    try:
        logo = ImageReader(io.BytesIO(bytes_identidade_visual('icmbio')))
    except (OSError, ValueError):
        logo = None

    def moldura(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(COR_VERDE)
        canvas.rect(0, pagina[1] - 9 * mm, pagina[0], 9 * mm, stroke=0, fill=1)
        canvas.setFillColor(COR_LIMA)
        canvas.rect(0, pagina[1] - 9.8 * mm, pagina[0], 0.8 * mm, stroke=0, fill=1)
        canvas.setFillColor(rl_cores.white)
        canvas.setFont('NGI-Bold', 8.5)
        canvas.drawString(margem, pagina[1] - 5.8 * mm, 'NGI ICMBio Carajás · Patrimônio Carajás')
        canvas.setFont('NGI', 8.5)
        canvas.drawRightString(pagina[0] - margem, pagina[1] - 5.8 * mm, 'Relatório final de bens · ' + convenio.nome[:70])
        canvas.setFillColor(COR_SUAVE)
        canvas.setFont('NGI', 7.2)
        canvas.drawString(margem, 8 * mm, f'Emitido em {emitido_txt} por {dados["emitido_por"]} · Código de verificação {dados["codigo"]}')
        canvas.setStrokeColor(COR_LINHA)
        canvas.line(margem, 11 * mm, pagina[0] - margem, 11 * mm)
        canvas.restoreState()

    doc = BaseDocTemplate(saida, pagesize=pagina, leftMargin=margem, rightMargin=margem, topMargin=16 * mm, bottomMargin=15 * mm,
                          title='Relatório final de bens · ' + convenio.nome, author='NGI ICMBio Carajás', subject='Relatório final do convênio')
    frame = Frame(margem, 15 * mm, largura, pagina[1] - 31 * mm, id='f', leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id='p', frames=[frame], onPage=moldura)])
    h = []

    # Capa e resumo
    cab_txt = [_p('RELATÓRIO FINAL DE BENS DO CONVÊNIO', ParagraphStyle('ey', fontName='NGI-Bold', fontSize=8, leading=10, textColor=COR_SUAVE)),
               Spacer(1, 3), _p(convenio.nome, E['titulo']), Spacer(1, 4),
               _p(f'Consolidação dos bens adquiridos com recursos deste convênio para o encerramento e a prestação de contas. Situação em {emitido_txt}.', E['sub'])]
    if logo:
        from reportlab.platypus import Image as RLImage
        iw, ih = logo.getSize()
        h.append(Table([[cab_txt, RLImage(io.BytesIO(bytes_identidade_visual('icmbio')), width=22 * mm, height=22 * mm * ih / iw)]],
                       colWidths=[largura - 30 * mm, 30 * mm], style=[('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                                                                       ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0)]))
    else:
        h.extend(cab_txt)
    h.append(Spacer(1, 10))

    def kpi(valor, rotulo, explicacao, alerta=False):
        cel = [_p(valor, ParagraphStyle('k', parent=E['kpi'], textColor=COR_ALERTA if alerta else COR_VERDE)),
               Spacer(1, 2), _p(rotulo, E['kpil']), Spacer(1, 1), _p(explicacao, E['kpis'])]
        return cel
    total = r['total']
    def parte(n):
        return f'{n} de {total}' if total else '0'
    kpis = [
        kpi(str(total), 'Bens adquiridos', 'Todos os bens vinculados ao convênio.'),
        kpi(str(r['ativos']), 'Ativos no acervo', f"{r['baixados']} já baixados com processo."),
        kpi(str(r['nao_localizados']), 'Não localizados', 'No último inventário de cada bem.', alerta=r['nao_localizados'] > 0),
        kpi(str(r['nunca']), 'Nunca conferidos', 'Bens que ainda não passaram por inventário.', alerta=r['nunca'] > 0),
        kpi(pct_txt(pct(r['com_nf'], total)), 'Com nota fiscal', parte(r['com_nf']) + ' com número ou arquivo da nota.'),
        kpi(pct_txt(pct(r['com_termo'], total)), 'Com termo de responsabilidade', parte(r['com_termo']) + f" · {r['com_aceite']} com aceite eletrônico."),
        kpi(pct_txt(pct(r['com_destinacao'], total)), 'Destinação definida', parte(r['com_destinacao']) + ' com destino para o encerramento.'),
        kpi(brl(r['valor']) if total else 'R$ 0,00', 'Valor de aquisição dos bens', 'Soma das notas fiscais' + (f"; {r['sem_valor']} sem valor." if r['sem_valor'] else '.')),
    ]
    lk = (largura - 3 * 8) / 4
    grade = Table([kpis[:4], kpis[4:]], colWidths=[lk] * 4, rowHeights=None, hAlign='LEFT')
    grade.setStyle(TableStyle([('BOX', (i, j), (i, j), 0.6, COR_LINHA) for i in range(4) for j in range(2)] +
                              [('BACKGROUND', (0, 0), (-1, -1), rl_cores.white), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                               ('LEFTPADDING', (0, 0), (-1, -1), 9), ('RIGHTPADDING', (0, 0), (-1, -1), 9),
                               ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 9)]))
    h.append(grade)
    h.append(Spacer(1, 10))
    guia = [[_p('Como ler este relatório', E['kpil'])]]
    for t in ('1. Inventários: quando os bens do convênio foram conferidos e o resultado de cada campanha.',
              '2. Relação dos bens: cada bem com nota fiscal, local, responsável, situação, última conferência, termo e destinação.',
              '3. Termos de responsabilidade: quem recebeu cada bem e se o aceite foi registrado.',
              '4. Pendências: o que ainda precisa ser resolvido antes de encerrar o convênio.',
              '5. Declaração e assinaturas: validação do relatório pelos responsáveis.'):
        guia.append([_p(t, E['bullet'])])
    caixa = Table(guia, colWidths=[largura])
    caixa.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), COR_CLARO), ('LEFTPADDING', (0, 0), (-1, -1), 10),
                               ('TOPPADDING', (0, 0), (-1, -1), 2.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
                               ('TOPPADDING', (0, 0), (-1, 0), 8), ('BOTTOMPADDING', (0, -1), (-1, -1), 8),
                               ('LINEBEFORE', (0, 0), (0, -1), 3, COR_VERDE_MEDIO)]))
    h.append(caixa)

    # 1. Inventários
    h.append(PageBreak())
    h.append(_p('1. Inventários', E['h2']))
    h.append(_p('Campanhas de inventário que incluíram bens deste convênio. Os números consideram apenas os bens do convênio. '
                'Acurácia = bens conferidos sem divergência ÷ bens do convênio na campanha.', E['nota']))
    h.append(Spacer(1, 6))
    if dados['inventarios']:
        cab = ['Inventário', 'Local', 'Abertura', 'Prazo', 'Encerramento', 'Situação', 'Bens', 'Conferidos', 'Divergência', 'Não localizados', 'Pendentes', 'Acurácia']
        linhas_inv = [[_p(c, E['cab']) for c in cab]]
        for i in dados['inventarios']:
            linhas_inv.append([_p(i['numero'] + '\n' + i['nome'], E['celp']), _p(i['local'], E['celp']), _p(data_br(i['abertura']), E['celp']),
                               _p(data_br(i['prazo']) or '—', E['celp']), _p(data_br(i['encerramento']) or 'Em andamento', E['celp']),
                               _p(i['status'], E['celp']), _p(i['total'], E['celp']), _p(i['conferidos'], E['celp']),
                               _p(i['divergencias'], E['celp']), _p(i['nao_localizados'], E['celp']), _p(i['pendentes'], E['celp']),
                               _p(pct_txt(i['acuracia']) + (' (parcial)' if i['pendentes'] else ''), E['celb'])])
        w = [31, 32, 19, 19, 27, 18, 12, 20, 22, 22, 19, 22]
        fator = largura / (sum(w) * mm)
        h.append(_tabela(linhas_inv, [x * mm * fator for x in w]))
        comissoes = [i for i in dados['inventarios'] if i['comissao']]
        if comissoes:
            h.append(Spacer(1, 5))
            for i in comissoes:
                h.append(_p(f"Comissão do {i['numero']}: {i['comissao']}", E['nota']))
    else:
        h.append(_p('Nenhum inventário incluiu bens deste convênio até a data de emissão.', E['txt']))

    # 2. Relação dos bens
    h.append(Spacer(1, 12))
    h.append(_p('2. Relação dos bens', E['h2']))
    h.append(_p('Todos os bens adquiridos com recursos do convênio. "Ativo" indica que o bem continua no acervo; "Baixado", que saiu do acervo com processo registrado.', E['nota']))
    h.append(Spacer(1, 6))
    cab = ['Nº', 'Patrimônio', 'Bem · marca · modelo · série', 'Nota fiscal · fornecedor · data', 'Valor', 'Local · responsável', 'Situação', 'Última conferência', 'Termo', 'Destinação']
    tab = [[_p(c, E['cab']) for c in cab]]
    for l in dados['linhas']:
        desc = ' · '.join(x for x in (l['marca'], l['modelo']) if x)
        tab.append([
            _p(l['n'], E['celp']), _p(l['patrimonio'], E['celb']),
            [_p(l['nome'], E['celb']), _p(desc + ('\nSérie ' + l['serie'] if l['serie'] else ''), E['celp'])],
            _p('\n'.join(x for x in (l['nf'] or 'Não informada', l['fornecedor'], data_br(l['data_aquisicao'])) if x), E['celp']),
            _p(brl(l['valor']) if l['valor'] is not None else '—', E['celp']),
            _p('\n'.join(x for x in (l['local'] + (' · ' + l['complemento'] if l['complemento'] else ''), l['responsavel']) if x), E['celp']),
            _p(l['situacao'], E['celp']), _p(l['ultima_conferencia'], E['celp']), _p(l['termo'], E['celp']),
            _p(l['destinacao'], E['celp'])])
    w = [8, 22, 46, 34, 19, 40, 22, 26, 25, 27]
    fator = largura / (sum(w) * mm)
    tabela_bens = _tabela(tab, [x * mm * fator for x in w])
    estilo_extra = []
    for i, l in enumerate(dados['linhas'], 1):
        if l['ultimo_resultado'] == 'Não localizado' and l['ativo']:
            estilo_extra.append(('TEXTCOLOR', (7, i), (7, i), COR_ALERTA))
            estilo_extra.append(('BACKGROUND', (7, i), (7, i), COR_ALERTA_FUNDO))
    if estilo_extra:
        tabela_bens.setStyle(TableStyle(estilo_extra))
    h.append(tabela_bens if dados['linhas'] else _p('Nenhum bem vinculado a este convênio.', E['txt']))

    # 3. Termos
    h.append(Spacer(1, 12))
    h.append(_p('3. Termos de responsabilidade', E['h2']))
    h.append(_p('Termos de responsabilidade e de movimentação emitidos para os bens do convênio, com a situação do aceite.', E['nota']))
    h.append(Spacer(1, 6))
    if dados['termos']:
        cab = ['Termo', 'Tipo', 'Emissão', 'Bem', 'Responsável', 'Emitido por', 'Aceite']
        tt = [[_p(c, E['cab']) for c in cab]]
        for t in dados['termos']:
            tt.append([_p(t['numero'], E['celb']), _p(t['tipo'], E['celp']), _p(data_br(t['emissao']), E['celp']),
                       _p(t['bem'] + ('\n' + t['patrimonio'] if t['patrimonio'] else ''), E['celp']), _p(t['responsavel'], E['celp']),
                       _p(t['emitente'], E['celp']), _p(t['aceite'], E['celp'])])
        w = [25, 32, 18, 55, 40, 33, 57]
        fator = largura / (sum(w) * mm)
        h.append(_tabela(tt, [x * mm * fator for x in w]))
    else:
        h.append(_p('Nenhum termo emitido para os bens deste convênio.', E['txt']))

    # 4. Pendências
    h.append(Spacer(1, 12))
    h.append(_p('4. Pendências para o encerramento', E['h2']))
    h.append(_p('Somente bens ativos. Cada grupo traz o que fazer para resolver.', E['nota']))
    h.append(Spacer(1, 6))
    algum = False
    for chave, titulo, acao in TITULOS_PENDENCIAS:
        itens = dados['pendencias'][chave]
        if not itens:
            continue
        algum = True
        nomes = [_p(f"{i['patrimonio']} – {i['nome']}", E['celp']) for i in itens]
        bloco = [[_p(f'{titulo} ({len(itens)})', E['kpil']), '', _p('O que fazer: ' + acao, E['kpis'])]]
        for k in range(0, len(nomes), 3):
            trio = nomes[k:k + 3]
            bloco.append(trio + [''] * (3 - len(trio)))
        tb = Table(bloco, colWidths=[largura / 3] * 3, repeatRows=1)
        tb.setStyle(TableStyle([('SPAN', (0, 0), (1, 0)), ('BACKGROUND', (0, 0), (-1, 0), COR_ALERTA_FUNDO),
                                ('BOX', (0, 0), (-1, -1), 0.6, COR_LINHA), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7),
                                ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                                ('TOPPADDING', (0, 0), (-1, 0), 6), ('BOTTOMPADDING', (0, 0), (-1, 0), 6)]))
        h.append(tb)
        h.append(Spacer(1, 6))
    if not algum:
        h.append(_p('Nenhuma pendência: todos os bens ativos têm nota fiscal, termo aceito, conferência no último ano e destinação definida.', E['txt']))

    # 5. Declaração e assinaturas
    decl = [Spacer(1, 10), _p('5. Declaração e assinaturas', E['h2']),
            _p(f'Declaramos que este relatório reflete os registros do sistema Patrimônio Carajás em {emitido_txt} para os bens adquiridos com recursos do '
               f'convênio {convenio.nome}, incluindo a situação de cada bem, os inventários realizados, os termos de responsabilidade emitidos e as pendências identificadas.', E['txt']),
            Spacer(1, 30)]
    c_txt = ParagraphStyle('ct', parent=E['txt'], alignment=1)
    c_rot = ParagraphStyle('cr', parent=E['kpil'], alignment=1)
    c_sub = ParagraphStyle('cs', parent=E['kpis'], alignment=1)
    papeis = ('Responsável pelo patrimônio', 'Coordenação do NGI ICMBio Carajás', 'Conferência / comissão')
    ass = [[_p('_' * 46, c_txt) for _ in papeis], [_p(x, c_rot) for x in papeis], [_p('Nome, matrícula e data', c_sub) for _ in papeis]]
    ta = Table(ass, colWidths=[largura / 3] * 3)
    ta.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6)]))
    decl.append(ta)
    decl.append(Spacer(1, 16))
    decl.append(_p(f'Código de verificação: {dados["codigo"]} · Integridade dos dados (SHA-256): {dados["integridade"]}', E['nota']))
    h.append(KeepTogether(decl))
    doc.build(h, canvasmaker=_CanvasNumerado)
    return saida.getvalue()


# ---------- Excel (XLSX gerado sem dependências extras) ----------
_XML_INVALIDO = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f]')


def _col(n):
    letras = ''
    while n:
        n, r = divmod(n - 1, 26)
        letras = chr(65 + r) + letras
    return letras


def _celula(ref, valor, estilo):
    if isinstance(valor, tuple):
        valor, estilo = valor
    if valor is None or valor == '':
        return f'<c r="{ref}" s="{estilo}"/>'
    if isinstance(valor, (int, float, Decimal)) and not isinstance(valor, bool):
        return f'<c r="{ref}" s="{estilo}"><v>{valor}</v></c>'
    if isinstance(valor, (date, datetime)):
        d = data_local(valor) if isinstance(valor, datetime) else valor
        return f'<c r="{ref}" s="4"><v>{(d - date(1899, 12, 30)).days}</v></c>'
    texto = _XML_INVALIDO.sub('', str(valor))
    return f'<c r="{ref}" s="{estilo}" t="inlineStr"><is><t xml:space="preserve">{xml_escape(texto)}</t></is></c>'


def _planilha_xml(titulo, subtitulo, colunas, linhas):
    """colunas: [(cabeçalho, largura, estilo)]; estilos: 2 texto, 3 moeda, 6 inteiro, 7 percentual."""
    partes = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
              '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">', '<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>']
    linha_cab = 4
    partes.append(f'<sheetViews><sheetView workbookViewId="0"><pane ySplit="{linha_cab}" topLeftCell="A{linha_cab + 1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>')
    partes.append('<cols>' + ''.join(f'<col min="{i}" max="{i}" width="{c[1]}" customWidth="1"/>' for i, c in enumerate(colunas, 1)) + '</cols>')
    partes.append('<sheetData>')
    partes.append(f'<row r="1" ht="24" customHeight="1">{_celula("A1", titulo, 5)}</row>')
    partes.append(f'<row r="2">{_celula("A2", subtitulo, 8)}</row>')
    partes.append(f'<row r="{linha_cab}" ht="30" customHeight="1">' + ''.join(_celula(f'{_col(i)}{linha_cab}', c[0], 1) for i, c in enumerate(colunas, 1)) + '</row>')
    for n, linha in enumerate(linhas, linha_cab + 1):
        partes.append(f'<row r="{n}">' + ''.join(_celula(f'{_col(i)}{n}', v, colunas[i - 1][2]) for i, v in enumerate(linha, 1)) + '</row>')
    partes.append('</sheetData>')
    if linhas:
        partes.append(f'<autoFilter ref="A{linha_cab}:{_col(len(colunas))}{linha_cab + len(linhas)}"/>')
    partes.append('<pageMargins left="0.4" right="0.4" top="0.5" bottom="0.5" header="0.3" footer="0.3"/>')
    partes.append('<pageSetup paperSize="9" orientation="landscape" fitToWidth="1" fitToHeight="0"/>')
    partes.append('</worksheet>')
    return ''.join(partes)


def gerar_xlsx(planilhas):
    estilos = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<numFmts count="2"><numFmt numFmtId="164" formatCode="&quot;R$&quot; #,##0.00"/><numFmt numFmtId="165" formatCode="dd/mm/yyyy"/></numFmts>'
        '<fonts count="5"><font><sz val="10"/><name val="Calibri"/></font><font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>'
        '<font><b/><sz val="15"/><color rgb="FF0E3B2B"/><name val="Calibri"/></font><font><i/><sz val="10"/><color rgb="FF55695D"/><name val="Calibri"/></font>'
        '<font><b/><sz val="10"/><name val="Calibri"/></font></fonts>'
        '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF0E3B2B"/><bgColor indexed="64"/></patternFill></fill></fills>'
        '<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>'
        '<border><left/><right/><top/><bottom style="thin"><color rgb="FFD5E2D9"/></bottom><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="10">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
        '<xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment vertical="top"/></xf>'
        '<xf numFmtId="165" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="top"/></xf>'
        '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        '<xf numFmtId="1" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="top"/></xf>'
        '<xf numFmtId="10" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="top"/></xf>'
        '<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        '<xf numFmtId="0" fontId="4" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
        '</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(planilhas) + 1))
            + '</Types>')
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            + ''.join(f'<sheet name="{xml_escape(p[0][:31])}" sheetId="{i}" r:id="rId{i}"/>' for i, p in enumerate(planilhas, 1))
            + '</sheets><definedNames>'
            + ''.join(f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i - 1}" hidden="1">\'{p[0][:31]}\'!$A$4:${_col(len(p[3]))}${4 + len(p[4])}</definedName>' for i, p in enumerate(planilhas, 1) if p[4])
            + '</definedNames></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(planilhas) + 1))
            + f'<Relationship Id="rId{len(planilhas) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('xl/styles.xml', estilos)
        for i, (nome, titulo, subtitulo, colunas, linhas) in enumerate(planilhas, 1):
            z.writestr(f'xl/worksheets/sheet{i}.xml', _planilha_xml(titulo, subtitulo, colunas, linhas))
    return saida.getvalue()


def gerar_xlsx_relatorio_final(dados):
    convenio, r = dados['convenio'], dados['resumo']
    total = r['total']
    sub = f'Convênio {convenio.nome} · emitido em {data_br(dados["emitido"], True)} por {dados["emitido_por"]} · código {dados["codigo"]}'
    resumo = [
        ('Bens adquiridos', total, 'Todos os bens vinculados ao convênio.'),
        ('Ativos no acervo', r['ativos'], 'Bens que continuam no acervo.'),
        ('Baixados', r['baixados'], 'Bens que saíram do acervo com processo registrado.'),
        ('Não localizados', r['nao_localizados'], 'Bens ativos não localizados no último inventário em que foram conferidos.'),
        ('Com divergência', r['divergencias'], 'Bens ativos com divergência no último inventário.'),
        ('Nunca conferidos', r['nunca'], 'Bens que ainda não passaram por inventário.'),
        ('Com nota fiscal', r['com_nf'], 'Bens com número ou arquivo da nota fiscal.'),
        ('Com termo de responsabilidade', r['com_termo'], 'Bens com termo de responsabilidade ou de movimentação emitido.'),
        ('Com aceite eletrônico', r['com_aceite'], 'Bens cujo termo foi aceito pelo link enviado ao e-mail.'),
        ('Com destinação definida', r['com_destinacao'], 'Bens com destino registrado para o encerramento.'),
        ('Valor de aquisição dos bens (R$)', float(r['valor']), 'Soma dos valores das notas fiscais' + (f"; {r['sem_valor']} bens sem valor." if r['sem_valor'] else '.')),
    ]
    linhas_resumo = [[rot, (val, 3) if isinstance(val, float) else val, (val / total) if total and isinstance(val, int) else None, exp]
                     for rot, val, exp in resumo]
    planilhas = [
        ('Resumo', 'Relatório final de bens do convênio', sub,
         [('Indicador', 34, 9), ('Quantidade', 16, 6), ('% dos bens', 12, 7), ('O que significa', 70, 2)], linhas_resumo),
    ]
    planilhas.append(('Bens', 'Relação dos bens', sub, [
        ('Nº', 6, 6), ('Patrimônio', 18, 2), ('Bem', 30, 9), ('Marca', 16, 2), ('Modelo', 18, 2), ('Número de série', 18, 2),
        ('Categoria', 16, 2), ('Nota fiscal', 16, 2), ('Fornecedor', 24, 2), ('Data de aquisição', 14, 4), ('Valor (R$)', 15, 3),
        ('Local', 24, 2), ('Sala / complemento', 18, 2), ('Responsável', 22, 2), ('Situação', 20, 2), ('Conservação', 13, 2),
        ('Último resultado de inventário', 20, 2), ('Data da última conferência', 14, 4), ('Termo', 22, 2),
        ('Destinação', 24, 2), ('Processo / referência da destinação', 26, 2)],
        [[l['n'], l['patrimonio'], l['nome'], l['marca'], l['modelo'], l['serie'], l['categoria'], l['nf'] or 'Não informada',
          l['fornecedor'], l['data_aquisicao'], float(l['valor']) if l['valor'] is not None else None, l['local'], l['complemento'],
          l['responsavel'], l['situacao'], l['conservacao'], l['ultimo_resultado'], l['ultima_data'], l['termo'], l['destinacao'],
          l['referencia']] for l in dados['linhas']]))
    planilhas.append(('Inventários', 'Inventários com bens do convênio', sub + ' · acurácia = conferidos ÷ bens do convênio na campanha', [
        ('Inventário', 14, 9), ('Nome', 26, 2), ('Local', 24, 2), ('Abertura', 13, 4), ('Prazo', 13, 4), ('Encerramento', 14, 4),
        ('Situação', 13, 2), ('Bens do convênio', 12, 6), ('Conferidos', 12, 6), ('Divergência', 12, 6), ('Não localizados', 13, 6),
        ('Pendentes', 11, 6), ('Acurácia', 11, 7), ('Comissão', 40, 2)],
        [[i['numero'], i['nome'], i['local'], i['abertura'], i['prazo'], i['encerramento'], i['status'], i['total'], i['conferidos'],
          i['divergencias'], i['nao_localizados'], i['pendentes'], (i['acuracia'] / 100) if i['acuracia'] is not None else None,
          i['comissao']] for i in dados['inventarios']]))
    planilhas.append(('Termos', 'Termos de responsabilidade', sub, [
        ('Termo', 14, 9), ('Tipo', 26, 2), ('Emissão', 13, 4), ('Bem', 30, 2), ('Patrimônio', 18, 2), ('Responsável', 26, 2),
        ('Emitido por', 22, 2), ('Aceite', 46, 2)],
        [[t['numero'], t['tipo'], t['emissao'], t['bem'], t['patrimonio'], t['responsavel'], t['emitente'], t['aceite']] for t in dados['termos']]))
    pend = []
    for chave, titulo, acao in TITULOS_PENDENCIAS:
        for i in dados['pendencias'][chave]:
            pend.append([titulo, i['patrimonio'], i['nome'], i['local'], i['responsavel'], acao])
    planilhas.append(('Pendências', 'Pendências para o encerramento', sub + ' · somente bens ativos', [
        ('Pendência', 34, 9), ('Patrimônio', 18, 2), ('Bem', 30, 2), ('Local', 24, 2), ('Responsável', 22, 2), ('O que fazer', 52, 2)], pend))
    return gerar_xlsx(planilhas)


@app.get('/encerramento/<int:convenio_id>/relatorio-final.pdf')
@login_obrigatorio
def relatorio_final_pdf(convenio_id):
    if not convenio_visivel(convenio_id):
        abort(404)
    convenio = carregar(Convenio, convenio_id)
    dados = dados_relatorio_final(convenio)
    return Response(gerar_pdf_relatorio_final(dados), mimetype='application/pdf',
                    headers={'Content-Disposition': "inline; filename*=UTF-8''" + quote(nome_arquivo_relatorio(convenio, 'pdf'))})


@app.get('/encerramento/<int:convenio_id>/relatorio-final.xlsx')
@login_obrigatorio
def relatorio_final_xlsx(convenio_id):
    if not convenio_visivel(convenio_id):
        abort(404)
    convenio = carregar(Convenio, convenio_id)
    dados = dados_relatorio_final(convenio)
    return Response(gerar_xlsx_relatorio_final(dados),
                    mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(nome_arquivo_relatorio(convenio, 'xlsx'))})


# ---------- PDF dos relatórios (dashboard, registros e indicadores) ----------
NOMES_FILTRO = dict(q='Busca', inicio='De', fim='Até', situacao='Situação', acervo='Acervo', tipo='Tipo', foco='Foco',
                    resultado_inventario='Resultado do inventário', grupo_convenio='Convênio', grupo_local='Local',
                    grupo_categoria='Categoria', dias='Bem parado há mais de (dias)')


def descrever_filtros(filtros):
    partes = []
    modelos = dict(convenio_id=(Convenio, 'Convênio'), base_id=(BaseLocal, 'Local'), categoria_id=(Categoria, 'Categoria'))
    for chave, valor in filtros.items():
        if valor in (None, '', 'quantidade') or chave in ('metrica', 'inventario_id'):
            continue
        if chave in modelos:
            obj = db.session.get(modelos[chave][0], valor)
            partes.append(f'{modelos[chave][1]}: {obj.nome if obj else valor}')
        elif chave in NOMES_FILTRO:
            if chave in ('inicio', 'fim'):
                try:
                    valor = date.fromisoformat(str(valor)).strftime('%d/%m/%Y')
                except ValueError:
                    pass
            if chave == 'acervo':
                valor = {'ativos': 'bens ativos', 'baixados': 'bens baixados', 'todos': 'todos os bens'}.get(valor, valor)
            partes.append(f'{NOMES_FILTRO[chave]}: {valor}')
    return ' · '.join(partes) or 'Sem filtros: todo o acervo do recorte padrão.'


def gerar_pdf_tabelas(titulo, subtitulo, blocos):
    """PDF A4 deitado com faixa verde, numeração de páginas e blocos de texto e tabelas.
    blocos: ('h2', texto) | ('txt', texto) | ('nota', texto) | ('tabela', [(cabeçalho, peso)], linhas)."""
    E = _estilos_pdf()
    pagina = landscape(A4)
    margem = 14 * mm
    largura = pagina[0] - 2 * margem
    saida = io.BytesIO()
    emitido = data_br(datetime.now(timezone.utc), True)
    autor = g.usuario.nome if getattr(g, 'usuario', None) else ''

    def moldura(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(COR_VERDE)
        canvas.rect(0, pagina[1] - 9 * mm, pagina[0], 9 * mm, stroke=0, fill=1)
        canvas.setFillColor(COR_LIMA)
        canvas.rect(0, pagina[1] - 9.8 * mm, pagina[0], 0.8 * mm, stroke=0, fill=1)
        canvas.setFillColor(rl_cores.white)
        canvas.setFont('NGI-Bold', 8.5)
        canvas.drawString(margem, pagina[1] - 5.8 * mm, 'NGI ICMBio Carajás · Patrimônio Carajás')
        canvas.setFont('NGI', 8.5)
        canvas.drawRightString(pagina[0] - margem, pagina[1] - 5.8 * mm, titulo[:80])
        canvas.setFillColor(COR_SUAVE)
        canvas.setFont('NGI', 7.2)
        canvas.drawString(margem, 8 * mm, f'Emitido em {emitido}' + (f' por {autor}' if autor else ''))
        canvas.setStrokeColor(COR_LINHA)
        canvas.line(margem, 11 * mm, pagina[0] - margem, 11 * mm)
        canvas.restoreState()

    doc = BaseDocTemplate(saida, pagesize=pagina, leftMargin=margem, rightMargin=margem, topMargin=16 * mm, bottomMargin=15 * mm,
                          title=titulo, author='NGI ICMBio Carajás', subject=titulo)
    frame = Frame(margem, 15 * mm, largura, pagina[1] - 31 * mm, id='f', leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id='p', frames=[frame], onPage=moldura)])
    h = [_p(titulo, E['titulo']), Spacer(1, 4), _p(subtitulo, E['sub']), Spacer(1, 10)]
    for bloco in blocos:
        if bloco[0] in ('h2', 'txt', 'nota'):
            h.append(_p(bloco[1], E[bloco[0]]))
            h.append(Spacer(1, 4 if bloco[0] == 'h2' else 6))
        else:
            colunas, linhas = bloco[1], bloco[2]
            soma = sum(peso for _, peso in colunas)
            larguras = [largura * peso / soma for _, peso in colunas]
            dados = [[_p(cab, E['cab']) for cab, _ in colunas]]
            for linha in linhas:
                dados.append([_p(v, E['celp']) for v in linha])
            if len(dados) == 1:
                dados.append([_p('Nenhum registro neste recorte.', E['celp'])] + [''] * (len(colunas) - 1))
            h.append(_tabela(dados, larguras))
            h.append(Spacer(1, 10))
    doc.build(h, canvasmaker=_CanvasNumerado)
    return saida.getvalue()


def resposta_pdf(conteudo, nome):
    return Response(conteudo, mimetype='application/pdf',
                    headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(nome)})


LIMITE_LINHAS_PDF = 3000


@app.get('/relatorios/dashboard.pdf')
@login_obrigatorio
def exportar_dashboard_pdf():
    consulta, filtros, erros, _ = consulta_dashboard()
    if erros:
        return Response(' '.join(erros), status=422, mimetype='text/plain')
    total = db.session.scalar(select(func.count()).select_from(consulta.order_by(None).subquery()))
    linhas = []
    for b in db.session.scalars(consulta.order_by(Bem.nome, Bem.id).limit(LIMITE_LINHAS_PDF)):
        linhas.append([b.nome, b.patrimonio, b.categoria or 'Sem categoria', b.convenio, b.local, b.responsavel,
                       'Baixado' if b.encerrado else b.situacao, data_br(b.data_aquisicao) if b.data_aquisicao else 'Não informada',
                       brl(b.valor) if b.valor is not None else 'Não informado',
                       b.nota_fiscal or ('Arquivo anexado' if b.nota_fiscal_anexada else 'Não informada'), 'Sim' if b.conferido else 'Não'])
    blocos = [('txt', f'{total} bens neste recorte. Filtros: {descrever_filtros(filtros)}')]
    if total > LIMITE_LINHAS_PDF:
        blocos.append(('nota', f'O PDF mostra os primeiros {LIMITE_LINHAS_PDF} bens em ordem alfabética. Use o CSV para a lista completa.'))
    blocos.append(('tabela', [('Bem', 2.2), ('Identificação', 1.2), ('Categoria', 1.1), ('Convênio', 1.3), ('Local', 1.2), ('Responsável', 1.3),
                              ('Situação', .9), ('Aquisição', .9), ('Valor', 1), ('Nota fiscal', 1), ('Conferido', .85)], linhas))
    pdf = gerar_pdf_tabelas('Bens patrimoniais', 'Dashboard patrimonial · bens do recorte selecionado na tela.', blocos)
    return resposta_pdf(pdf, f'bens-patrimoniais-{hoje_local().isoformat()}.pdf')


TITULOS_REGISTROS = dict(bens='Bens patrimoniais', movimentacoes='Movimentações', baixas='Processos de baixa', inventario='Conferências de inventário')


@app.get('/relatorios/operacoes.pdf')
@login_obrigatorio
def exportar_relatorio_pdf():
    consulta, filtros, colunas, erros = consulta_relatorio()
    if erros:
        return Response(' '.join(erros), status=422, mimetype='text/plain')
    total = db.session.scalar(select(func.count()).select_from(consulta.order_by(None).subquery()))
    linhas = [[v if v is not None else '' for v in linha]
              for linha in linhas_relatorio(db.session.scalars(consulta.limit(LIMITE_LINHAS_PDF)), filtros['tipo'])]
    blocos = [('txt', f'{total} registros. Filtros: {descrever_filtros(filtros)}')]
    if total > LIMITE_LINHAS_PDF:
        blocos.append(('nota', f'O PDF mostra os primeiros {LIMITE_LINHAS_PDF} registros. Use o CSV para a lista completa.'))
    blocos.append(('tabela', [(c, 2 if i == 1 or (filtros['tipo'] == 'bens' and i == 0) else 1) for i, c in enumerate(colunas)], linhas))
    titulo = 'Relatório de registros · ' + TITULOS_REGISTROS[filtros['tipo']]
    pdf = gerar_pdf_tabelas(titulo, 'Registros do sistema conforme os filtros aplicados na tela.', blocos)
    return resposta_pdf(pdf, f'relatorio-{filtros["tipo"]}-{hoje_local().isoformat()}.pdf')


@app.get('/relatorios/indicadores.pdf')
@login_obrigatorio
def exportar_indicadores_pdf():
    filtros = filtros_indicadores()
    dados = calcular_indicadores(filtros)
    campanha = dados['campanha']
    blocos = [('txt', 'Filtros: ' + descrever_filtros(filtros)
               + (f' · Inventário de referência: INV-{campanha.id:06d} {campanha.nome} ({campanha.status.lower()})' if campanha else ' · Nenhum inventário registrado.'))]
    grupos = (('Inventário', dados['ind_inventario']), ('Uso dos bens', dados['ind_uso']), ('Termos de responsabilidade', dados['ind_termos']))
    for nome, inds in grupos:
        if not inds:
            continue
        blocos.append(('h2', nome))
        blocos.append(('tabela', [('Indicador', 1.3), ('Resultado', .8), ('Situação', .8), ('O que mede', 2.6), ('Como é calculado', 1.8), ('Cálculo neste recorte', 1.9), ('Exemplo', 2)],
                       [[i['nome'], i['valor'], i['faixa'], i['mede'], i['formula'], i['calculo'], i['exemplo']] for i in inds]))
    if dados['historico']:
        blocos.append(('h2', 'Histórico dos inventários'))
        blocos.append(('tabela', [('Inventário', 2), ('Local', 1.5), ('Situação', .9), ('Data', .9), ('Bens', .6), ('Acurácia', .8), ('Não localizados', 1), ('Divergências', 1)],
                       [[f'INV-{h["id"]:06d} · {h["nome"]}', h['local'], h['status'], data_br(h['data']), h['total'], h['acuracia'], h['nao_localizados'], h['divergencias']]
                        for h in dados['historico']]))
    for nome, (bens, dias) in dados['listas'].items():
        if not bens:
            continue
        blocos.append(('h2', f'{nome} ({len(bens)})'))
        extra = [('Dias', .5)] if dias else []
        linhas = [[b.numero_ngi or b.plaqueta_original or 'Sem plaqueta', b.nome, ' '.join(x for x in (b.marca, b.modelo) if x), b.local,
                   b.convenio, b.responsavel, b.situacao] + ([dias.get(b.id, '')] if dias else []) for b in bens[:LIMITE_LINHAS_PDF]]
        blocos.append(('tabela', [('Patrimônio', 1), ('Bem', 2), ('Marca / modelo', 1.4), ('Local', 1.3), ('Convênio', 1.3), ('Responsável', 1.3), ('Situação', .9)] + extra, linhas))
    pdf = gerar_pdf_tabelas('Indicadores de gestão', 'Resultado de cada indicador, o que ele mede, a fórmula, o cálculo com os dados do sistema e um exemplo.', blocos)
    return resposta_pdf(pdf, f'indicadores-{hoje_local().isoformat()}.pdf')


@app.get('/encerramento/<int:convenio_id>/exportar.csv')
@login_obrigatorio
def exportar_encerramento(convenio_id):
    convenio = carregar(Convenio, convenio_id)

    @stream_with_context
    def gerar():
        out = io.StringIO()
        writer = csv.writer(out, delimiter=';', lineterminator='\r\n')
        yield '\ufeff'
        writer.writerow(
            [
                'Convênio',
                'Bem',
                'Identificação',
                'Local',
                'Responsável',
                'Acervo',
                'Destinação registrada',
                'Processo / referência',
                'Nota fiscal',
            ]
        )
        yield out.getvalue()
        out.seek(0)
        out.truncate(0)
        consulta = (
            select(Bem, DestinacaoConvenio)
            .outerjoin(
                DestinacaoConvenio,
                (DestinacaoConvenio.bem_id == Bem.id)
                & (DestinacaoConvenio.convenio_id == convenio_id),
            )
            .where(Bem.convenio_id == convenio_id)
            .order_by(Bem.id)
            .execution_options(yield_per=200)
        )
        for bem, d in db.session.execute(consulta):
            linha = [
                convenio.nome,
                bem.nome,
                bem.patrimonio,
                bem.local,
                bem.responsavel,
                'Baixado' if bem.encerrado else 'Ativo',
                d.destino if d else 'Não definida',
                d.referencia if d else '',
                bem.nota_fiscal or ('Arquivo anexado' if bem.nota_fiscal_anexada else 'Não informada'),
            ]
            writer.writerow(
                [
                    (
                        ("'" + str(v))
                        if str(v).lstrip().startswith(('=', '+', '-', '@'))
                        or str(v).startswith(('\n', '\r', '\t'))
                        else str(v)
                    )
                    for v in linha
                ]
            )
            yield out.getvalue()
            out.seek(0)
            out.truncate(0)

    return Response(
        gerar(),
        content_type='text/csv; charset=utf-8',
        headers={
            'Content-Disposition': f'attachment; filename=destinacao_convenio_{convenio_id}.csv'
        },
    )


CATEGORIAS_TEMPLATE=r'''
<div class="list-heading"><div><h1>Categorias dos bens</h1><p>Organize o patrimônio por tipo: móveis, eletrodomésticos, veículos e outras categorias.</p></div></div>{% include 'registro_navegacao' %}{% include 'op_erros' %}
<div class="registry-workspace">{% if not registro_formulario %}<section class="panel registry-list"><div class="panelhead"><div><h2>Categorias cadastradas</h2><p>{{ total_registros }} registros · 25 por página</p></div></div>{% include 'registro_filtros' %}<div class="tablewrap"><table><thead><tr><th>Categoria</th><th>Descrição</th><th>Bens vinculados</th><th>Situação</th><th></th></tr></thead><tbody>{% for c in registros %}<tr><td><strong>{{ c.nome }}</strong></td><td>{{ c.descricao or '—' }}</td><td>{{ contagens_categoria.get(c.id,0) }}</td><td><span class="badge">{{ 'Ativa' if c.ativo else 'Inativa' }}</span></td><td>{% if not usuario.leitura %}<a class="text-action" href="{{ url_for('editar_categoria',categoria_id=c.id) }}">Editar</a>{% endif %}</td></tr>{% else %}<tr><td colspan="5" class="list-empty">Nenhuma categoria encontrada. Use Cadastrar categoria para começar.</td></tr>{% endfor %}</tbody></table></div>{% include 'registro_paginacao' %}</section>{% else %}<section class="form-section registry-form"><h2>{{ 'Editar categoria' if categoria_editando else 'Cadastrar categoria' }}</h2><form method="post" action="{{ url_for('editar_categoria',categoria_id=categoria_editando.id) if categoria_editando else url_for('categorias_cadastro') }}"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><input type="hidden" name="revisao" value="{{ valores.get('revisao',categoria_editando.revisao if categoria_editando else 0) }}"><div class="fields"><div class="field wide"><label for="categoria-nome">Nome da categoria *</label><input id="categoria-nome" name="nome" required minlength="2" maxlength="100" value="{{ valores.get('nome','') }}" placeholder="Ex.: Móveis, eletrodomésticos, veículos"></div><div class="field wide"><label for="categoria-descricao">Descrição</label><textarea id="categoria-descricao" name="descricao" maxlength="500">{{ valores.get('descricao','') }}</textarea></div>{% if categoria_editando %}<div class="field"><label for="categoria-ativo">Disponibilidade para novos bens</label><select id="categoria-ativo" name="ativo"><option value="sim" {{ 'selected' if valores.get('ativo','sim')=='sim' }}>Ativa</option><option value="nao" {{ 'selected' if valores.get('ativo')=='nao' }}>Inativa</option></select></div>{% endif %}</div><p class="hint">Categorias inativas mantêm os bens já vinculados. O nome atualizado aparece na relação de bens e nos relatórios.</p><div class="dialog-actions"><a class="btn" href="{{ url_for('categorias_cadastro') }}">Cancelar</a><button class="btn primary">{{ 'Salvar alterações' if categoria_editando else 'Cadastrar categoria' }}</button></div></form></section>{% endif %}</div>
'''


def tela_categorias(valores=None,erros=None,registro=None,status=200):
    contexto=contexto_registro('categorias',valores,erros,registro)
    pag=pagina_registros(Categoria,Categoria.nome,formulario=contexto['registro_formulario'])
    ids=[r.id for r in pag['registros']]
    contagens=dict(db.session.execute(select(Bem.categoria_id,func.count()).where(Bem.categoria_id.in_(ids)).group_by(Bem.categoria_id)).all()) if ids else {}
    return render_template_string(TEMPLATE,cadastros_page=True,cadastro_tipo='categorias',cadastro_titulo='Categorias',
        formulario=False,bem=None,valores=valores or {},erros=erros or [],categoria_editando=registro,
        contagens_categoria=contagens,**contexto,**pag,**contexto_painel()),status


def validar_categoria(form):
    erros = []
    nome = ' '.join(form.get('nome', '').split())
    descricao = form.get('descricao', '').strip()
    if not 2 <= len(nome) <= 100:
        erros.append('Informe um nome de categoria com 2 a 100 caracteres.')
    if len(descricao) > 500:
        erros.append('A descrição deve ter até 500 caracteres.')
    return dict(nome=nome, nome_chave=nome.casefold(), descricao=descricao), erros


@app.route('/cadastros/categorias', methods=['GET', 'POST'])
@login_obrigatorio
def categorias_cadastro():
    if request.method == 'GET':
        return tela_categorias()
    dados, erros = validar_categoria(request.form)
    if erros:
        return tela_categorias(request.form, erros, status=422)
    try:
        db.session.add(Categoria(**dados))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return tela_categorias(request.form, ['Já existe uma categoria com esse nome.'], status=409)
    flash('Categoria cadastrada. Ela já pode ser selecionada nos bens.')
    return redirect(url_for('categorias_cadastro'))


@app.route('/cadastros/categorias/<int:categoria_id>/editar', methods=['GET', 'POST'])
@login_obrigatorio
def editar_categoria(categoria_id):
    categoria = carregar(Categoria, categoria_id, request.method == 'POST')
    if request.method == 'GET':
        return tela_categorias(
            dict(
                nome=categoria.nome,
                descricao=categoria.descricao,
                ativo='sim' if categoria.ativo else 'nao',
                revisao=categoria.revisao,
            ),
            registro=categoria,
        )
    dados, erros = validar_categoria(request.form)
    if request.form.get('revisao') != str(categoria.revisao):
        erros.append('A categoria foi alterada em outra tela. Reabra a edição.')
    if request.form.get('ativo') not in ('sim', 'nao'):
        erros.append('Selecione a disponibilidade da categoria.')
    if erros:
        db.session.rollback()
        return tela_categorias(request.form, erros, categoria, 422)
    if dados['nome'] != categoria.nome:
        for bem in db.session.scalars(
            select(Bem).where(Bem.categoria_id == categoria.id).order_by(Bem.id).with_for_update()
        ).all():
            antes = snapshot(bem)
            bem.categoria = dados['nome']
            bem.revisao += 1
            bem.conferido = False
            bem.atualizado_em = datetime.now(timezone.utc)
            registrar_evento(bem, 'Atualização da categoria', antes)
    for campo, valor in dados.items():
        setattr(categoria, campo, valor)
    categoria.ativo = request.form.get('ativo') == 'sim'
    categoria.revisao += 1
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return tela_categorias(
            request.form, ['Já existe outra categoria com esse nome.'], categoria, 409
        )
    flash('Categoria atualizada. Os vínculos existentes foram preservados.')
    return redirect(url_for('categorias_cadastro'))


COORDENACOES_TEMPLATE=r'''
<div class="list-heading"><div><h1>Coordenações</h1><p>Cadastre as coordenações com o nome completo e a sigla, que é a forma usada no dia a dia.</p></div></div>{% include 'registro_navegacao' %}{% include 'op_erros' %}
<div class="registry-workspace">{% if not registro_formulario %}<section class="panel registry-list"><div class="panelhead"><div><h2>Coordenações cadastradas</h2><p>{{ total_registros }} registros · 25 por página</p></div></div>{% include 'registro_filtros' %}<div class="tablewrap"><table><thead><tr><th>Sigla</th><th>Nome da coordenação</th><th>Situação</th><th></th></tr></thead><tbody>{% for c in registros %}<tr><td><span class="coord-sigla">{{ c.sigla }}</span></td><td>{{ c.nome }}</td><td><span class="badge {{ '' if c.ativo else 'warn' }}">{{ 'Ativa' if c.ativo else 'Inativa' }}</span></td><td>{% if not usuario.leitura %}<a class="text-action" href="{{ url_for('editar_coordenacao',coordenacao_id=c.id) }}">Editar</a>{% endif %}</td></tr>{% else %}<tr><td colspan="4" class="list-empty">Nenhuma coordenação encontrada. Use Cadastrar coordenação para começar.</td></tr>{% endfor %}</tbody></table></div>{% include 'registro_paginacao' %}</section>{% else %}<section class="form-section registry-form"><h2>{{ 'Editar coordenação' if coordenacao_editando else 'Cadastrar coordenação' }}</h2><form method="post" action="{{ url_for('editar_coordenacao',coordenacao_id=coordenacao_editando.id) if coordenacao_editando else url_for('coordenacoes_cadastro') }}"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><input type="hidden" name="revisao" value="{{ valores.get('revisao',coordenacao_editando.revisao if coordenacao_editando else 0) }}"><div class="fields"><div class="field"><label for="coord-sigla">Sigla *</label><input id="coord-sigla" name="sigla" required minlength="2" maxlength="20" value="{{ valores.get('sigla','') }}" placeholder="Ex.: COPS" autocapitalize="characters" style="text-transform:uppercase"><small>É como a coordenação aparece nas listas e relatórios.</small></div><div class="field wide"><label for="coord-nome">Nome da coordenação *</label><input id="coord-nome" name="nome" required minlength="3" maxlength="160" value="{{ valores.get('nome','') }}" placeholder="Ex.: Coordenação de Operação e Suporte"></div>{% if coordenacao_editando %}<div class="field"><label for="coord-ativo">Situação</label><select id="coord-ativo" name="ativo"><option value="sim" {{ 'selected' if valores.get('ativo','sim')=='sim' }}>Ativa</option><option value="nao" {{ 'selected' if valores.get('ativo')=='nao' }}>Inativa</option></select></div>{% endif %}</div><p class="hint">A sigla é gravada em letras maiúsculas e não pode se repetir. Coordenações inativas continuam no histórico.</p><div class="dialog-actions"><a class="btn" href="{{ url_for('coordenacoes_cadastro') }}">Cancelar</a><button class="btn primary">{{ 'Salvar alterações' if coordenacao_editando else 'Cadastrar coordenação' }}</button></div></form></section>{% endif %}</div>
'''


def tela_coordenacoes(valores=None, erros=None, registro=None, status=200):
    contexto = contexto_registro('coordenacoes', valores, erros, registro)
    pag = pagina_registros(Coordenacao, Coordenacao.sigla, formulario=contexto['registro_formulario'])
    return render_template_string(TEMPLATE, cadastros_page=True, cadastro_tipo='coordenacoes', cadastro_titulo='Coordenações',
        formulario=False, bem=None, valores=valores or {}, erros=erros or [], coordenacao_editando=registro,
        **contexto, **pag, **contexto_painel()), status


def validar_coordenacao(form):
    erros = []
    nome = ' '.join(form.get('nome', '').split())
    sigla = ''.join(form.get('sigla', '').split()).upper()
    if not 3 <= len(nome) <= 160:
        erros.append('Informe o nome da coordenação com 3 a 160 caracteres.')
    if not 2 <= len(sigla) <= 20:
        erros.append('Informe a sigla com 2 a 20 caracteres.')
    elif not re.fullmatch(r'[0-9A-ZÀ-Ý/.\-]+', sigla):
        erros.append('A sigla aceita letras, números, barra, ponto e hífen, sem espaços.')
    return dict(nome=nome, nome_chave=nome.casefold(), sigla=sigla, sigla_chave=sigla.casefold()), erros


def conflito_coordenacao(dados, atual_id=None):
    for coluna, valor, mensagem in ((Coordenacao.sigla_chave, dados['sigla_chave'], 'Já existe uma coordenação com essa sigla.'),
                                    (Coordenacao.nome_chave, dados['nome_chave'], 'Já existe uma coordenação com esse nome.')):
        existente = db.session.scalar(select(Coordenacao.id).where(coluna == valor))
        if existente and existente != atual_id:
            return mensagem
    return None


@app.route('/cadastros/coordenacoes', methods=['GET', 'POST'])
@login_obrigatorio
def coordenacoes_cadastro():
    if request.method == 'GET':
        return tela_coordenacoes()
    dados, erros = validar_coordenacao(request.form)
    if not erros:
        conflito = conflito_coordenacao(dados)
        if conflito:
            return tela_coordenacoes(request.form, [conflito], status=409)
    if erros:
        return tela_coordenacoes(request.form, erros, status=422)
    try:
        db.session.add(Coordenacao(**dados))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return tela_coordenacoes(request.form, ['Já existe uma coordenação com essa sigla ou nome.'], status=409)
    flash(f"Coordenação {dados['sigla']} cadastrada.")
    return redirect(url_for('coordenacoes_cadastro'))


@app.route('/cadastros/coordenacoes/<int:coordenacao_id>/editar', methods=['GET', 'POST'])
@login_obrigatorio
def editar_coordenacao(coordenacao_id):
    coordenacao = carregar(Coordenacao, coordenacao_id, request.method == 'POST')
    if request.method == 'GET':
        return tela_coordenacoes(dict(nome=coordenacao.nome, sigla=coordenacao.sigla,
                                      ativo='sim' if coordenacao.ativo else 'nao', revisao=coordenacao.revisao),
                                 registro=coordenacao)
    dados, erros = validar_coordenacao(request.form)
    if request.form.get('revisao') != str(coordenacao.revisao):
        erros.append('A coordenação foi alterada em outra tela. Reabra a edição.')
    if request.form.get('ativo') not in ('sim', 'nao'):
        erros.append('Selecione a situação da coordenação.')
    if not erros:
        conflito = conflito_coordenacao(dados, coordenacao.id)
        if conflito:
            db.session.rollback()
            return tela_coordenacoes(request.form, [conflito], coordenacao, 409)
    if erros:
        db.session.rollback()
        return tela_coordenacoes(request.form, erros, coordenacao, 422)
    for campo, valor in dados.items():
        setattr(coordenacao, campo, valor)
    coordenacao.ativo = request.form.get('ativo') == 'sim'
    coordenacao.revisao += 1
    db.session.execute(Bem.__table__.update().where(Bem.coordenacao_id == coordenacao.id).values(coordenacao=coordenacao.sigla))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return tela_coordenacoes(request.form, ['Já existe outra coordenação com essa sigla ou nome.'], coordenacao, 409)
    flash(f"Coordenação {coordenacao.sigla} atualizada.")
    return redirect(url_for('coordenacoes_cadastro'))


DASHBOARD_RELATORIOS_TEMPLATE=r'''
<div class="list-heading"><div><h1>Dashboard patrimonial</h1><p>Analise os bens por convênio, local e categoria. Clique nos resultados para consultar os registros.</p></div><div class="pdf-btns"><a class="btn" href="{{ link_exportar }}">Exportar CSV</a><a class="btn primary" href="{{ link_exportar|replace('/relatorios/dashboard.csv','/relatorios/dashboard.pdf') }}">Baixar PDF</a></div></div><nav class="registry-navigation" aria-label="Relatórios"><a href="{{ url_for('relatorios') }}" class="{{ 'current' if request.endpoint=='relatorios' }}">Dashboard patrimonial</a><a href="{{ url_for('indicadores_gestao') }}" class="{{ 'current' if request.endpoint=='indicadores_gestao' }}">Indicadores de gestão</a><a href="{{ url_for('relatorio_operacional') }}" class="{{ 'current' if request.endpoint=='relatorio_operacional' }}">Relatório de registros</a></nav>{% include 'op_erros' %}
<section class="panel analytics-filters"><form method="get" action="{{ url_for('relatorios') }}"><div class="analytics-filter-grid">{% for chave,label,opcoes in [('convenio_id','Convênio',convenios_dashboard),('base_id','Base / local',bases_dashboard),('categoria_id','Categoria',categorias_dashboard)] %}<div class="field"><label for="dash-{{ chave }}">{{ label }}</label><select id="dash-{{ chave }}" name="{{ chave }}"><option value="">Todos</option>{% for o in opcoes %}<option value="{{ o.id }}" {{ 'selected' if filtros[chave]==o.id }}>{{ o.nome }}{{ ' · Inativo' if not o.ativo else '' }}</option>{% endfor %}</select></div>{% endfor %}
<div class="field"><label for="dash-situacao">Situação de uso</label><select id="dash-situacao" name="situacao"><option value="">Todas</option>{% for st in opcoes_situacao %}<option {{ 'selected' if filtros.situacao==st }}>{{ st }}</option>{% endfor %}</select></div><div class="field"><label for="dash-acervo">Acervo</label><select id="dash-acervo" name="acervo">{% for chave,label in [('ativos','Ativos'),('baixados','Baixados'),('todos','Todos')] %}<option value="{{ chave }}" {{ 'selected' if filtros.acervo==chave }}>{{ label }}</option>{% endfor %}</select></div>
{% for chave,label in [('inicio','Aquisição a partir de'),('fim','Aquisição até')] %}<div class="field"><label for="dash-{{ chave }}">{{ label }}</label><input id="dash-{{ chave }}" type="date" name="{{ chave }}" value="{{ filtros[chave] }}"></div>{% endfor %}
</div>
<div class="analytics-filter-bottom"><div class="field"><label for="dash-busca">Pesquisar bem, série ou plaqueta</label><input id="dash-busca" name="q" maxlength="120" value="{{ filtros.q }}" placeholder="Opcional"></div><button class="btn primary">Aplicar filtros</button><a class="btn" href="{{ url_for('relatorios') }}">Limpar filtros</a></div></form><p class="hint">Todos os indicadores consideram os mesmos filtros. O período corresponde à data de aquisição; bens sem data ficam fora quando um período é informado. Os gráficos mostram quantidades. O valor de aquisição fica no indicador acima dos gráficos, sem depreciação.</p></section>
{% if filtros.foco or filtros.resultado_inventario or filtros.grupo_convenio or filtros.grupo_local or filtros.grupo_categoria %}<div class="callout"><strong>Recorte adicional selecionado</strong><p>{{ filtros.resultado_inventario or filtros.grupo_convenio or filtros.grupo_local or ('Sem categoria' if filtros.grupo_categoria=='__sem_categoria__' else filtros.grupo_categoria) or {'pendentes':'Conferência pendente','atrasados':'Devolução atrasada','sem_valor':'Valor não informado'}.get(filtros.foco,'') }}</p><a class="content-link" href="{{ url_for('relatorios') }}">Limpar recortes</a></div>{% endif %}
<section class="analytics-kpis" aria-label="Indicadores do patrimônio">{% for k in indicadores %}<a href="{{ k.url }}" class="analytics-kpi"><span>{{ k.titulo }}</span><strong>{{ k.numero }}</strong><small>{{ k.descricao }}</small><span class="analytics-kpi-action">Consultar bens →</span></a>{% endfor %}</section>
{% if not total_dash %}<div class="panel analytics-empty"><h2>Nenhum bem corresponde aos filtros</h2><p>Ajuste o convênio, local, categoria ou período para visualizar os resultados.</p></div>{% endif %}
<div class="analytics-charts">
<section class="panel analytics-chart r28-local" aria-labelledby="r28-local-title"><div class="analytics-chart-title"><h2 id="r28-local-title">Bens por local</h2><span>Quantidade de bens</span></div><p class="analytics-chart-note">Até 10 locais com mais bens. Clique em uma coluna para consultar os registros.</p>{% set locais_grafico=graficos[1].itens %}{% if locais_grafico %}<div class="r28-column-scroll" tabindex="0" role="region" aria-label="Gráfico de colunas por local; role horizontalmente para ver todos os locais"><div class="r28-columns" style="--r28-count:{{ locais_grafico|length }}">{% for item in locais_grafico %}<a href="{{ item.url }}" class="r28-column" aria-label="{{ item.nome }}: {{ item.quantidade }} bens" title="{{ item.nome }}: {{ item.quantidade }} bens"><div class="r28-column-frame"><div class="r28-column-fill" style="height:{{ item.largura }}%"><strong>{{ item.quantidade }}</strong></div></div><span>{{ item.nome }}</span></a>{% endfor %}</div></div><p class="r28-column-hint">Cada coluna representa um local. Deslize o gráfico quando houver mais locais.</p>{% else %}<p class="analytics-no-data">Sem dados para este filtro.</p>{% endif %}</section>
<section class="panel analytics-chart r28-convenios" aria-labelledby="r28-convenios-title"><div class="analytics-chart-title"><h2 id="r28-convenios-title">Bens por convênio</h2><span>Quantidade de bens</span></div><p class="analytics-chart-note">Até 10 convênios com mais bens. Clique em uma barra para consultar os registros.</p><div class="analytics-bars">{% for item in graficos[0].itens %}<a class="analytics-bar" data-paleta="{{ 'global-iii' if item.nome|lower=='global iii' else 'horizontes' if item.nome|lower=='horizontes' else '' }}" href="{{ item.url }}" aria-label="{{ item.nome }}: {{ item.quantidade }} bens"><div><span>{{ item.nome }}</span><strong>{{ item.quantidade }}</strong></div><div class="analytics-track"><span style="width:{{ item.largura }}%"></span></div></a>{% else %}<p class="analytics-no-data">Sem dados para este filtro.</p>{% endfor %}</div></section>
<section class="panel analytics-chart r28-categorias" aria-labelledby="r28-categorias-title"><div class="analytics-chart-title"><h2 id="r28-categorias-title">Bens por categoria</h2><span>Quantidade de bens</span></div><p class="analytics-chart-note">Categorias com mais bens primeiro. Clique em uma linha para consultar os registros.</p>{% if partes_categoria %}<div class="g-ranking">{% for parte in partes_categoria %}{% if parte.url %}<a class="g-rank-linha" href="{{ parte.url }}" aria-label="{{ parte.nome }}: {{ parte.quantidade }} bens, {{ '%.0f'|format(parte.percentual) }}%">{% else %}<div class="g-rank-linha g-rank-outros">{% endif %}<div class="g-rank-topo"><span class="g-rank-nome">{{ parte.nome }}</span><span class="g-rank-valor"><strong>{{ parte.quantidade }}</strong><small>{{ '%.0f'|format(parte.percentual) }}%</small></span></div><div class="g-rank-trilho"><span style="width:{{ [parte.percentual,1.5]|max }}%"></span></div>{% if parte.url %}</a>{% else %}</div>{% endif %}{% endfor %}</div>{% else %}<p class="analytics-no-data">Sem dados para este filtro.</p>{% endif %}{% if outras_categorias %}<p class="analytics-chart-note">Exibidas as 10 maiores categorias; as demais estão em “Outras categorias”.</p>{% endif %}</section>
<section class="panel analytics-chart g-inventario"><div class="analytics-chart-title"><h2>Resultados do inventário</h2><span>Quantidade de bens</span></div><p class="analytics-chart-note">Último resultado registrado de cada bem deste recorte.</p>{% if partes_inventario %}{% set conferidos = (partes_inventario|selectattr("nome","equalto","Conferido")|map(attribute="quantidade")|sum) %}<div class="g-destaque"><strong>{{ '%.0f'|format(conferidos / total_dash * 100 if total_dash else 0) }}%</strong><span>dos bens conferidos sem divergência<br><small>{{ conferidos }} de {{ total_dash }} bens</small></span></div><div class="g-segmentos" role="img" aria-label="{% for p in partes_inventario %}{{ p.nome }} {{ p.quantidade }}{{ ', ' if not loop.last }}{% endfor %}">{% for p in partes_inventario %}<a href="{{ p.url }}" class="g-seg" style="flex:{{ p.quantidade }} 1 0;background:{{ p.cor }}" title="{{ p.nome }}: {{ p.quantidade }} bens"></a>{% endfor %}</div><div class="g-lista">{% for p in partes_inventario %}<a href="{{ p.url }}" class="g-item"><span class="g-ponto" style="background:{{ p.cor }}"></span><span class="g-item-nome">{{ p.nome }}</span><strong>{{ p.quantidade }}</strong><small>{{ '%.0f'|format(p.percentual) }}%</small></a>{% endfor %}</div>{% else %}<p class="analytics-no-data">Nenhum resultado.</p>{% endif %}</section>
<section class="panel analytics-chart analytics-wide"><div class="analytics-chart-title"><h2>Bens por situação</h2><span>Quantidade de bens</span></div><div class="analytics-situations">{% for item in status_bens %}<a class="analytics-bar" data-paleta="{{ 'global-iii' if item.nome|lower=='global iii' else 'horizontes' if item.nome|lower=='horizontes' else '' }}" href="{{ item.url }}"><div><span>{{ item.nome }}</span><strong>{{ item.quantidade }}</strong></div><div class="analytics-track"><span style="width:{{ item.largura }}%"></span></div><small>{{ '%.0f'|format(item.largura) }}% do recorte selecionado</small></a>{% else %}<p class="analytics-no-data">Sem dados.</p>{% endfor %}</div></section></div>
<div class="analytics-footer-links"><a class="content-link" href="{{ detalhar() }}">Consultar todos os bens deste recorte</a><a class="content-link" href="{{ url_for('relatorio_operacional') }}">Consultar registros de movimentações, baixas e inventário</a></div>
'''
DASHBOARD_BENS_TEMPLATE=r'''
<a class="back" href="{{ voltar_dashboard }}">← Voltar ao dashboard</a><div class="list-heading"><div><h1>Bens do indicador</h1><p>{{ quantidade_operacao }} registros correspondem ao recorte selecionado.</p></div><div class="pdf-btns"><a class="btn" href="{{ link_exportar }}">Exportar CSV</a><a class="btn primary" href="{{ link_exportar|replace('/relatorios/dashboard.csv','/relatorios/dashboard.pdf') }}">Baixar PDF</a></div></div>{% include 'op_erros' %}<section class="panel"><div class="tablewrap"><table><thead><tr><th>Bem / identificação</th><th>Categoria</th><th>Convênio</th><th>Local</th><th>Responsável</th><th>Valor de aquisição</th><th></th></tr></thead><tbody>{% for b in rows %}<tr><td><strong>{{ b.nome }}</strong><small class="table-sub">{{ b.patrimonio }}</small></td><td>{{ b.categoria or 'Sem categoria' }}</td><td>{{ b.convenio }}</td><td>{{ b.local }}</td><td>{{ b.responsavel }}</td><td>{{ b.valor|brl }}</td><td><a class="text-action" href="{{ url_for('ficha',bem_id=b.id,consulta=1) }}">Abrir ficha</a></td></tr>{% else %}<tr><td colspan="7" class="list-empty">Nenhum bem encontrado.</td></tr>{% endfor %}</tbody></table></div>{% include 'op_paginacao' %}</section>
'''

# Dashboard patrimonial: filtros compartilhados entre indicadores, gráficos e CSV.
def resultado_inventario_sql(status_item):
    return case((Bem.conferido.is_(True),'Conferido'),
        (status_item.in_(('Divergência','Não localizado')),status_item),
        (status_item=='Pendente','Pendente'),(status_item=='Conferido','Revisão necessária'),else_='Sem conferência')


def consulta_dashboard():
    dados = {
        campo: request.args.get(campo, '').strip()
        for campo in (
            'q',
            'inicio',
            'fim',
            'situacao',
            'grupo_convenio',
            'grupo_local',
            'grupo_categoria',
            'resultado_inventario',
            'foco',
        )
    }
    dados['q'] = dados['q'][:120]
    erros = []
    for campo in ('base_id', 'convenio_id', 'categoria_id'):
        valor = request.args.get(campo, '')
        dados[campo] = inteiro(valor)
        if valor and dados[campo] is None:
            erros.append('Confira o filtro ' + campo.replace('_id', '') + '.')
    dados['acervo'] = request.args.get('acervo', 'ativos')
    if dados['acervo'] not in ('ativos', 'baixados', 'todos'):
        dados['acervo'] = 'ativos'
    # Gráficos representam quantidade; valor de aquisição permanece no indicador.
    dados['metrica'] = 'quantidade'
    if dados['situacao'] not in SITUACOES:
        dados['situacao'] = ''
    consulta = select(Bem)
    if dados['acervo'] != 'todos':
        consulta = consulta.where(Bem.encerrado.is_(dados['acervo'] == 'baixados'))
    for campo in ('base_id', 'convenio_id', 'categoria_id'):
        if dados[campo]:
            consulta = consulta.where(getattr(Bem, campo) == dados[campo])
    if dados['q']:
        consulta = consulta.where(
            or_(
                *(
                    c.icontains(dados['q'], autoescape=True)
                    for c in (Bem.nome, Bem.serie, Bem.numero_ngi, Bem.plaqueta_original)
                )
            )
        )
    if dados['situacao']:
        consulta = consulta.where(Bem.situacao == dados['situacao'])
    for campo, coluna in (
        ('grupo_convenio', Bem.convenio),
        ('grupo_local', Bem.local),
        ('grupo_categoria', Bem.categoria),
    ):
        if dados[campo]:
            consulta = consulta.where(
                coluna
                == (
                    ''
                    if campo == 'grupo_categoria' and dados[campo] == '__sem_categoria__'
                    else dados[campo]
                )
            )
    datas = {}
    for campo in ('inicio', 'fim'):
        try:
            datas[campo] = date.fromisoformat(dados[campo]) if dados[campo] else None
        except ValueError:
            erros.append('Data de ' + campo + ' inválida.')
            datas[campo] = None
    if datas['inicio'] and datas['fim'] and datas['inicio'] > datas['fim']:
        erros.append('A data inicial deve ser anterior ou igual à final.')
    if datas['inicio']:
        consulta = consulta.where(Bem.data_aquisicao >= datas['inicio'])
    if datas['fim']:
        consulta = consulta.where(Bem.data_aquisicao <= datas['fim'])
    atrasado = (
        select(Movimento.id)
        .where(
            Movimento.bem_id == Bem.id,
            Movimento.status == 'Concluída',
            Movimento.tipo.in_(('Entrega temporária', 'Manutenção')),
            Movimento.devolvido_em.is_(None),
            Movimento.previsao_retorno < hoje_local(),
        )
        .exists()
    )
    if dados['foco'] == 'pendentes':
        consulta = consulta.where(Bem.conferido.is_(False))
    elif dados['foco'] == 'atrasados':
        consulta = consulta.where(atrasado)
    elif dados['foco'] == 'sem_valor':
        consulta = consulta.where(Bem.valor.is_(None))
    else:
        dados['foco'] = ''
    resultados = (
        'Conferido',
        'Divergência',
        'Não localizado',
        'Pendente',
        'Revisão necessária',
        'Sem conferência',
    )
    if dados['resultado_inventario'] in resultados:
        ultimo_status = (
            select(ItemInventario.status)
            .where(ItemInventario.bem_id == Bem.id)
            .order_by(ItemInventario.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        consulta = consulta.where(
            resultado_inventario_sql(ultimo_status) == dados['resultado_inventario']
        )
    else:
        dados['resultado_inventario'] = ''
    if erros:
        consulta = consulta.where(False)
    return consulta, dados, erros, atrasado


def links_dashboard(filtros, **alteracoes):
    args = dict(filtros)
    args.update(alteracoes)
    return {k: v for k, v in args.items() if v not in ('', None)}


@app.get('/relatorios')
@login_obrigatorio
def relatorios():
    consulta, filtros, erros, atrasado = consulta_dashboard()
    ids = consulta.with_only_columns(Bem.id).order_by(None)
    resumo = db.session.execute(
        select(
            func.count(Bem.id),
            func.coalesce(func.sum(Bem.valor), 0),
            func.coalesce(func.sum(case((Bem.valor.is_(None), 1), else_=0)), 0),
            func.coalesce(func.sum(case((Bem.conferido.is_(False), 1), else_=0)), 0),
        ).where(Bem.id.in_(ids))
    ).one()
    total, valor, sem_valor, pendentes = resumo
    vencidos = db.session.scalar(select(func.count(Bem.id)).where(Bem.id.in_(ids), atrasado)) or 0

    def detalhar(**alteracoes):
        return url_for('dashboard_bens', **links_dashboard(filtros, **alteracoes))

    def agrupar(coluna, chave):
        medida = (
            func.coalesce(func.sum(Bem.valor), 0)
            if filtros['metrica'] == 'valor'
            else func.count(Bem.id)
        )
        resultado = db.session.execute(
            select(coluna, func.count(Bem.id), func.coalesce(func.sum(Bem.valor), 0))
            .where(Bem.id.in_(ids))
            .group_by(coluna)
            .order_by(medida.desc(), coluna)
            .limit(10)
        ).all()
        maximo = max(
            (float(v) if filtros['metrica'] == 'valor' else n for _, n, v in resultado), default=0
        )
        return [
            dict(
                nome=nome
                or ('Sem categoria' if chave == 'grupo_categoria' else 'Não identificado'),
                quantidade=n,
                valor=v,
                largura=(
                    round((float(v) if filtros['metrica'] == 'valor' else n) / maximo * 100, 2)
                    if maximo
                    else 0
                ),
                url=detalhar(
                    **{chave: nome or ('__sem_categoria__' if chave == 'grupo_categoria' else '')}
                ),
            )
            for nome, n, v in resultado
        ]

    graficos = [
        dict(titulo='Bens por convênio', itens=agrupar(Bem.convenio, 'grupo_convenio')),
        dict(titulo='Bens por local', itens=agrupar(Bem.local, 'grupo_local')),
        dict(titulo='Bens por categoria', itens=agrupar(Bem.categoria, 'grupo_categoria')),
    ]
    cores_categoria = [
        '#15573F',
        '#6FCF97',
        '#C7F26B',
        '#0B3325',
        '#8EBDA4',
        '#4A8060',
        '#D7E8B3',
        '#638C77',
        '#B7D5C3',
        '#7DA34F',
    ]
    partes_categoria = []
    offset_categoria = 0
    for i, item in enumerate(graficos[2]['itens']):
        percentual = item['quantidade'] / total * 100 if total else 0
        partes_categoria.append(
            dict(
                nome=item['nome'],
                quantidade=item['quantidade'],
                percentual=percentual,
                offset=offset_categoria,
                cor=cores_categoria[i % len(cores_categoria)],
                url=item['url'],
            )
        )
        offset_categoria += percentual
    outras_categorias = total - sum(item['quantidade'] for item in graficos[2]['itens'])
    if outras_categorias:
        partes_categoria.append(
            dict(
                nome='Outras categorias',
                quantidade=outras_categorias,
                percentual=outras_categorias / total * 100,
                offset=offset_categoria,
                cor='#D5DED6',
                url=None,
            )
        )
    situacao_grafico = case((Bem.encerrado.is_(True), 'Baixado'), else_=Bem.situacao)
    situacoes = db.session.execute(
        select(situacao_grafico, func.count())
        .where(Bem.id.in_(ids))
        .group_by(situacao_grafico)
        .order_by(func.count().desc(), situacao_grafico)
    ).all()
    status_bens = [
        dict(
            nome=nome,
            quantidade=n,
            url=(
                detalhar(acervo='baixados', situacao='')
                if nome == 'Baixado'
                else detalhar(situacao=nome)
            ),
            largura=round(n / total * 100, 2) if total else 0,
        )
        for nome, n in situacoes
    ]
    ultimos = (
        select(ItemInventario.bem_id, func.max(ItemInventario.id).label('ultimo_id'))
        .where(ItemInventario.bem_id.in_(ids))
        .group_by(ItemInventario.bem_id)
        .subquery()
    )
    estado = resultado_inventario_sql(ItemInventario.status)
    inventario = db.session.execute(
        select(estado.label('resultado'), func.count(Bem.id))
        .outerjoin(ultimos, Bem.id == ultimos.c.bem_id)
        .outerjoin(ItemInventario, ItemInventario.id == ultimos.c.ultimo_id)
        .where(Bem.id.in_(ids))
        .group_by(estado)
        .order_by(func.count(Bem.id).desc(), estado)
    ).all()
    cores = {
        'Conferido': '#246e50',
        'Divergência': '#d08a2e',
        'Não localizado': '#bb4944',
        'Pendente': '#8da597',
        'Revisão necessária': '#8b71a9',
        'Sem conferência': '#d4ded6',
    }
    partes = []
    offset = 0
    for nome, n in inventario:
        percentual = n / total * 100 if total else 0
        partes.append(
            dict(
                nome=nome,
                quantidade=n,
                percentual=percentual,
                offset=offset,
                cor=cores[nome],
                url=detalhar(resultado_inventario=nome),
            )
        )
        offset += percentual
    ordem_resultado = ['Conferido', 'Divergência', 'Revisão necessária', 'Não localizado', 'Pendente', 'Sem conferência']
    partes.sort(key=lambda p: ordem_resultado.index(p['nome']) if p['nome'] in ordem_resultado else 99)
    indicadores = [
        dict(
            titulo='Quantidade de bens',
            numero=str(total),
            descricao='Bens que atendem aos filtros',
            url=detalhar(),
        ),
        dict(
            titulo='Valor de aquisição',
            numero=brl(valor),
            descricao=f'{sem_valor} bens sem valor informado',
            url=detalhar(),
        ),
        dict(
            titulo='Conferência pendente',
            numero=str(pendentes),
            descricao='Sem conferência válida no cadastro atual',
            url=detalhar(foco='pendentes'),
        ),
        dict(
            titulo='Devoluções atrasadas',
            numero=str(vencidos),
            descricao='Bens com retorno previsto vencido',
            url=detalhar(foco='atrasados'),
        ),
    ]
    return tela_operacao(
        'relatorios',
        'dashboard_relatorios',
        'Dashboard de relatórios',
        status=422 if erros else 200,
        filtros=filtros,
        erros=erros,
        indicadores=indicadores,
        total_dash=total,
        valor_dash=valor,
        graficos=graficos,
        status_bens=status_bens,
        partes_inventario=partes,
        partes_categoria=partes_categoria,
        outras_categorias=outras_categorias,
        detalhar=detalhar,
        link_exportar=url_for('exportar_dashboard', **links_dashboard(filtros)),
        bases_dashboard=db.session.scalars(select(BaseLocal).order_by(BaseLocal.nome)).all(),
        convenios_dashboard=db.session.scalars(select(Convenio).order_by(Convenio.nome)).all(),
        categorias_dashboard=db.session.scalars(select(Categoria).order_by(Categoria.nome)).all(),
        opcoes_situacao=SITUACOES,
    )


FAIXAS_INDICADORES = {
    # (limite bom, limite atenção, maior é melhor)
    'acuracia': (95, 85, True), 'nao_localizados': (2, 5, False), 'divergencias': (5, 10, False),
    'parados': (5, 15, False), 'sem_conferencia': (10, 30, False), 'termos': (90, 70, True),
}


def pct(parte, total):
    return (parte * 100.0 / total) if total else None


def pct_txt(valor):
    return '—' if valor is None else (f'{valor:.1f}'.replace('.', ',') + '%')


def faixa_indicador(chave, valor):
    if valor is None:
        return 'Sem dados', 'neutro'
    bom, atencao, maior = FAIXAS_INDICADORES[chave]
    if (valor >= bom) if maior else (valor <= bom):
        return 'Bom', 'ok'
    if (valor >= atencao) if maior else (valor <= atencao):
        return 'Atenção', 'warn'
    return 'Crítico', 'bad'


def utc(valor):
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def filtros_indicadores():
    dias = inteiro(request.args.get('dias')) or 180
    return dict(convenio_id=inteiro(request.args.get('convenio_id')), base_id=inteiro(request.args.get('base_id')),
                inventario_id=inteiro(request.args.get('inventario_id')), dias=dias if dias in (90, 180, 365) else 180)


def resumo_campanha(campanha, convenio_id=None):
    consulta = select(ItemInventario.status, func.count()).where(ItemInventario.inventario_id == campanha.id)
    if convenio_id:
        consulta = consulta.join(Bem, Bem.id == ItemInventario.bem_id).where(Bem.convenio_id == convenio_id)
    contagem = dict(db.session.execute(consulta.group_by(ItemInventario.status)).all())
    total = sum(contagem.values())
    return total, contagem


def bens_resumidos(bens, dias=None):
    return [dict(id=b.id, nome=b.nome, patrimonio=b.numero_ngi or b.plaqueta_original or 'Sem plaqueta',
                 local=b.local or 'Local não informado', situacao=b.situacao,
                 dias=dias.get(b.id) if dias else None) for b in bens[:100]]


def calcular_indicadores(filtros, listas_completas=False):
    agora = datetime.now(timezone.utc)
    campanhas_q = select(CampanhaInventario)
    if filtros['base_id']:
        campanhas_q = campanhas_q.where(CampanhaInventario.base_id == filtros['base_id'])
    campanhas = db.session.scalars(campanhas_q.order_by(CampanhaInventario.id.desc()).limit(30)).all()
    campanha = next((c for c in campanhas if c.id == filtros['inventario_id']), None)
    if campanha is None and campanhas:
        campanha = next((c for c in campanhas if c.status == 'Encerrado'), campanhas[0])

    ind_inventario, historico, listas = [], [], {}
    if campanha:
        total, contagem = resumo_campanha(campanha, filtros['convenio_id'])
        conferidos = contagem.get('Conferido', 0)
        nao_loc = contagem.get('Não localizado', 0)
        diverg = contagem.get('Divergência', 0)
        pendentes = contagem.get('Pendente', 0)
        verificados = total - pendentes
        link = lambda st: url_for('inventario_detalhe', inventario_id=campanha.id, status=st)
        v = pct(conferidos, total)
        f = faixa_indicador('acuracia', v)
        ind_inventario.append(dict(chave='acuracia', nome='Acurácia do inventário', valor=pct_txt(v), barra=round(v or 0), faixa=f[0], classe=f[1],
            detalhe=f'{conferidos} de {total} bens conferidos sem divergência',
            mede='Quanto o cadastro bate com a realidade: o bem estava no local, com o responsável e no estado registrados.',
            formula='bens conferidos ÷ bens do inventário × 100',
            calculo=f'{conferidos} ÷ {total} × 100 = {pct_txt(v)}' + (f'. Ainda há {pendentes} pendentes, que contam como não confirmados.' if pendentes else '.'),
            exemplo='Inventário de 120 bens com 114 conferidos sem divergência: 114 ÷ 120 = 95,0%. No almoxarifado, a mesma ideia é a acurácia de estoque: itens cujo saldo físico bate com o sistema ÷ itens contados.',
            referencia='IN SEDAP nº 205/1988, item 8 (inventário físico).', link=None, link_rotulo='', bens=[]))
        v = pct(nao_loc, total)
        f = faixa_indicador('nao_localizados', v)
        ind_inventario.append(dict(chave='nao_localizados', nome='Bens não localizados', valor=pct_txt(v), barra=round(v or 0), faixa=f[0], classe=f[1],
            detalhe=f'{nao_loc} de {total} bens não encontrados',
            mede='Bens que estão no cadastro, mas não foram encontrados na conferência. Precisam de apuração.',
            formula='bens não localizados ÷ bens do inventário × 100',
            calculo=f'{nao_loc} ÷ {total} × 100 = {pct_txt(v)}.',
            exemplo='Relatório de inventário da AGU (2025): 150 bens não localizados em 2.739 bens de uma unidade = 5,48%.',
            referencia='Indicador usado nos relatórios de inventário da Administração Pública Federal (AGU, 2025).',
            link=link('Não localizado') if nao_loc else None, link_rotulo='Ver os bens no inventário', bens=[]))
        v = pct(diverg, total)
        f = faixa_indicador('divergencias', v)
        ind_inventario.append(dict(chave='divergencias', nome='Divergências cadastrais', valor=pct_txt(v), barra=round(v or 0), faixa=f[0], classe=f[1],
            detalhe=f'{diverg} de {total} bens com algo diferente do cadastro',
            mede='Bens encontrados, mas em outro local, com outro responsável ou em outro estado. O cadastro e o termo precisam ser atualizados.',
            formula='bens com divergência ÷ bens do inventário × 100',
            calculo=f'{diverg} ÷ {total} × 100 = {pct_txt(v)}.',
            exemplo='6 bens achados em outra sala ou com outro responsável, num inventário de 120: 6 ÷ 120 = 5,0%.',
            referencia='IN SEDAP nº 205/1988, itens 7.13.3 e 8.2 (atualizar termo e registro do estado).',
            link=link('Divergência') if diverg else None, link_rotulo='Ver os bens no inventário', bens=[]))
        v = pct(verificados, total)
        completa = total and pendentes == 0
        ind_inventario.append(dict(chave='cobertura', nome='Cobertura da conferência', valor=pct_txt(v), barra=round(v or 0),
            faixa='Completa' if completa else ('Sem dados' if not total else 'Em andamento'), classe='ok' if completa else ('neutro' if not total else 'warn'),
            detalhe=f'{verificados} de {total} bens já verificados',
            mede='Quanto do inventário já foi feito. Só compare acurácia entre campanhas completas.',
            formula='bens verificados (conferidos, divergentes ou não localizados) ÷ bens do inventário × 100',
            calculo=f'{verificados} ÷ {total} × 100 = {pct_txt(v)}' + (f'. Faltam {pendentes}.' if pendentes else '.'),
            exemplo='90 de 120 bens verificados = 75%: a campanha ainda tem 30 bens pendentes.',
            referencia='IN SEDAP nº 205/1988, item 8.1 (inventário anual e demais tipos).',
            link=link('Pendente') if pendentes else None, link_rotulo='Ver os pendentes', bens=[]))
        for c in campanhas[:8]:
            t, cont = resumo_campanha(c, filtros['convenio_id'])
            a = pct(cont.get('Conferido', 0), t)
            historico.append(dict(id=c.id, nome=c.nome, local=c.local, status=c.status, data=c.encerrado_em or c.criado_em, total=t,
                acuracia=pct_txt(a), classe_acuracia=faixa_indicador('acuracia', a)[1] if c.status == 'Encerrado' else 'neutro',
                nao_localizados=f"{cont.get('Não localizado', 0)} ({pct_txt(pct(cont.get('Não localizado', 0), t))})",
                divergencias=f"{cont.get('Divergência', 0)} ({pct_txt(pct(cont.get('Divergência', 0), t))})"))
        if pendentes:
            # Campanha incompleta: resultado parcial, sem faixa de cor para não alarmar à toa.
            for t in ind_inventario[:3]:
                t['faixa'], t['classe'] = 'Parcial', 'neutro'
                t['calculo'] += ' Resultado parcial: a campanha ainda tem bens pendentes.' if 'pendentes' not in t['calculo'] else ''

    # Bens ativos do recorte e a última atividade de cada um
    bens_q = select(Bem).where(Bem.encerrado.is_(False))
    if filtros['convenio_id']:
        bens_q = bens_q.where(Bem.convenio_id == filtros['convenio_id'])
    if filtros['base_id']:
        bens_q = bens_q.where(Bem.base_id == filtros['base_id'])
    bens = db.session.scalars(bens_q.order_by(Bem.nome, Bem.id)).all()
    ids = [b.id for b in bens]
    ultima_mov, ultima_conf = {}, {}
    if ids:
        for bem_id, quando in db.session.execute(select(Movimento.bem_id, func.max(Movimento.concluido_em))
                .where(Movimento.bem_id.in_(ids), Movimento.status == 'Concluída', Movimento.concluido_em.is_not(None)).group_by(Movimento.bem_id)):
            ultima_mov[bem_id] = utc(quando)
        for bem_id, quando in db.session.execute(select(ItemInventario.bem_id, func.max(ItemInventario.conferido_em))
                .where(ItemInventario.bem_id.in_(ids), ItemInventario.status != 'Pendente', ItemInventario.conferido_em.is_not(None))
                .group_by(ItemInventario.bem_id)):
            ultima_conf[bem_id] = utc(quando)
    dias_parado, dias_sem_conf = {}, {}
    for b in bens:
        criado = utc(b.criado_em) or agora
        atividade = max(x for x in (criado, ultima_mov.get(b.id), ultima_conf.get(b.id)) if x)
        dias_parado[b.id] = max(0, (agora - atividade).days)
        dias_sem_conf[b.id] = max(0, (agora - (ultima_conf.get(b.id) or criado)).days)
    total_ativos = len(bens)
    parados = sorted((b for b in bens if b.situacao in ('Disponível', 'Manutenção') and dias_parado[b.id] > filtros['dias']),
                     key=lambda b: -dias_parado[b.id])
    disponiveis = sum(1 for b in parados if b.situacao == 'Disponível')
    sem_conf = sorted((b for b in bens if dias_sem_conf[b.id] > 365), key=lambda b: -dias_sem_conf[b.id])
    listas['Bem parado'] = (parados, dias_parado)
    listas['Sem conferência há mais de 1 ano'] = (sem_conf, dias_sem_conf)

    v = pct(len(parados), total_ativos)
    f = faixa_indicador('parados', v)
    ind_uso = [dict(chave='parados', nome='Bens parados', valor=str(len(parados)), barra=round(v or 0), faixa=f[0], classe=f[1],
        detalhe=f'{pct_txt(v)} dos {total_ativos} bens ativos · {disponiveis} disponíveis e {len(parados) - disponiveis} em manutenção',
        mede=f'Bens com situação Disponível (sem uso) ou Manutenção e sem movimentação nem conferência há mais de {filtros["dias"]} dias. Disponível por muito tempo pode ser bem ocioso; manutenção longa pede avaliar se é recuperável ou antieconômico.',
        formula=f'bens Disponível ou Manutenção com última atividade há mais de {filtros["dias"]} dias',
        calculo=f'{len(parados)} de {total_ativos} bens ativos = {pct_txt(v)}.',
        exemplo='Projetor Disponível, sem movimentação nem conferência há 200 dias: entra na lista. Um bem Em uso ou Em campo não entra, mesmo parado no mesmo lugar.',
        referencia='Decreto nº 12.785/2025, art. 3º (ocioso, recuperável, antieconômico) e IN SEDAP nº 205/1988, item 11.2.1 (ociosos disponíveis para cessão).',
        link=None, link_rotulo='', bens=bens_resumidos(parados, dias_parado))]
    v = pct(len(sem_conf), total_ativos)
    f = faixa_indicador('sem_conferencia', v)
    ind_uso.append(dict(chave='sem_conferencia', nome='Sem conferência há mais de 1 ano', valor=str(len(sem_conf)), barra=round(v or 0), faixa=f[0], classe=f[1],
        detalhe=f'{pct_txt(v)} dos {total_ativos} bens ativos',
        mede='Bens que não passaram por conferência em inventário nos últimos 365 dias (ou desde o cadastro, se nunca foram conferidos). São os que mais correm risco de virar não localizados.',
        formula='bens ativos cuja última conferência (ou cadastro) tem mais de 365 dias',
        calculo=f'{len(sem_conf)} de {total_ativos} bens ativos = {pct_txt(v)}.',
        exemplo='Bem cadastrado em 2024 e nunca conferido em inventário: entra na lista até ser conferido.',
        referencia='IN SEDAP nº 205/1988, item 8.1, a (inventário anual).',
        link=None, link_rotulo='', bens=bens_resumidos(sem_conf, dias_sem_conf)))

    # Termos de responsabilidade e aceite eletrônico
    com_termo, com_aceite = set(), set()
    if ids:
        com_termo = set(db.session.scalars(select(Documento.bem_id).where(Documento.bem_id.in_(ids), Documento.tipo.in_(TIPOS_ACEITE)).distinct()))
        com_termo |= set(db.session.scalars(select(TermoBem.bem_id).where(TermoBem.bem_id.in_(ids)).distinct()))
        com_aceite = set(db.session.scalars(select(Documento.bem_id).join(AceiteTermo, AceiteTermo.documento_id == Documento.id)
            .where(Documento.bem_id.in_(ids), AceiteTermo.status == 'Aceito').distinct()))
        com_aceite |= set(db.session.scalars(select(TermoBem.bem_id).join(AceiteTermo, AceiteTermo.documento_id == TermoBem.documento_id)
            .where(TermoBem.bem_id.in_(ids), AceiteTermo.status == 'Aceito').distinct()))
    sem_termo = [b for b in bens if b.id not in com_termo]
    listas['Sem termo de responsabilidade'] = (sem_termo, None)
    v = pct(len(com_termo), total_ativos)
    f = faixa_indicador('termos', v)
    ind_termos = [dict(chave='termos', nome='Cobertura de termos', valor=pct_txt(v), barra=round(v or 0), faixa=f[0], classe=f[1],
        detalhe=f'{len(com_termo)} de {total_ativos} bens com termo · {len(sem_termo)} sem termo',
        mede='Bens ativos com termo de responsabilidade ou de movimentação emitido, ou seja, com responsável formalizado.',
        formula='bens com termo emitido ÷ bens ativos × 100',
        calculo=f'{len(com_termo)} ÷ {total_ativos} × 100 = {pct_txt(v)}.',
        exemplo='80 bens ativos, 72 com termo emitido: 72 ÷ 80 = 90%. Os 8 restantes estão sem responsável formalizado.',
        referencia='IN SEDAP nº 205/1988, item 7.11 (nenhum equipamento sem carga e termo).',
        link=None, link_rotulo='', bens=bens_resumidos(sem_termo))]
    v = pct(len(com_aceite), len(com_termo))
    ind_termos.append(dict(chave='aceite', nome='Termos com aceite eletrônico', valor=pct_txt(v), barra=round(v or 0),
        faixa='Informativo' if v is not None else 'Sem dados', classe='neutro',
        detalhe=f'{len(com_aceite)} de {len(com_termo)} bens com termo aceito pelo link do e-mail',
        mede='Dos bens com termo, quantos já têm o aceite eletrônico registrado. Os demais dependem de assinatura em papel anexada ou de aceite pendente.',
        formula='bens com termo aceito eletronicamente ÷ bens com termo × 100',
        calculo=f'{len(com_aceite)} ÷ {len(com_termo)} × 100 = {pct_txt(v)}.' if com_termo else 'Nenhum termo emitido neste recorte.',
        exemplo='72 bens com termo e 54 com aceite eletrônico: 54 ÷ 72 = 75%.',
        referencia='Aceite eletrônico do termo de responsabilidade (Termos e documentos).',
        link=url_for('documentos'), link_rotulo='Abrir termos e documentos', bens=[]))
    return dict(campanhas=campanhas, campanha=campanha, ind_inventario=ind_inventario, historico=historico,
                ind_uso=ind_uso, ind_termos=ind_termos, total_ativos=total_ativos, listas=listas)


def args_indicadores(filtros, campanha):
    args = {k: filtros[k] for k in ('convenio_id', 'base_id') if filtros[k]}
    args['dias'] = filtros['dias']
    if campanha:
        args['inventario_id'] = campanha.id
    return args


@app.get('/relatorios/indicadores')
@login_obrigatorio
def indicadores_gestao():
    filtros = filtros_indicadores()
    dados = calcular_indicadores(filtros)
    dados.pop('listas')
    return tela_operacao('relatorios', 'indicadores', 'Indicadores de gestão', filtros=filtros,
        convenios_ind=db.session.scalars(select(Convenio).order_by(Convenio.nome)).all(),
        bases_ind=db.session.scalars(select(BaseLocal).order_by(BaseLocal.nome)).all(),
        link_csv=url_for('exportar_indicadores', **args_indicadores(filtros, dados['campanha'])), **dados)


@app.get('/relatorios/indicadores.csv')
@login_obrigatorio
def exportar_indicadores():
    filtros = filtros_indicadores()
    dados = calcular_indicadores(filtros)

    def seguro(valor):
        valor = str(valor if valor is not None else '')
        if valor.lstrip().startswith(('=', '+', '-', '@')) or valor.startswith(('\t', '\r', '\n')):
            valor = "'" + valor
        return valor

    out = io.StringIO()
    escritor = csv.writer(out, delimiter=';', lineterminator='\r\n')
    escritor.writerow(['Indicador', 'Patrimônio', 'Bem', 'Marca / modelo', 'Número de série', 'Base / local', 'Convênio', 'Responsável', 'Situação', 'Dias'])
    for indicador, (bens, dias) in dados['listas'].items():
        for b in bens:
            escritor.writerow([seguro(x) for x in (indicador, b.numero_ngi or b.plaqueta_original or 'Sem plaqueta', b.nome,
                ' '.join(x for x in (b.marca, b.modelo) if x), b.serie, b.local, b.convenio, b.responsavel, b.situacao,
                dias.get(b.id) if dias else '')])
    campanha = dados['campanha']
    if campanha:
        consulta = select(ItemInventario, Bem).join(Bem, Bem.id == ItemInventario.bem_id).where(
            ItemInventario.inventario_id == campanha.id, ItemInventario.status.in_(('Não localizado', 'Divergência')))
        if filtros['convenio_id']:
            consulta = consulta.where(Bem.convenio_id == filtros['convenio_id'])
        for item, b in db.session.execute(consulta.order_by(ItemInventario.status, Bem.nome)):
            escritor.writerow([seguro(x) for x in (f'{item.status} no INV-{campanha.id:06d}', b.numero_ngi or b.plaqueta_original or 'Sem plaqueta',
                b.nome, ' '.join(x for x in (b.marca, b.modelo) if x), b.serie, b.local, b.convenio, b.responsavel, b.situacao, '')])
    nome = 'indicadores-' + datetime.now(timezone(timedelta(hours=-3))).strftime('%Y-%m-%d') + '.csv'
    return Response('﻿' + out.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{nome}"'})


@app.get('/relatorios/bens')
@login_obrigatorio
def dashboard_bens():
    consulta,filtros,erros,_=consulta_dashboard()
    return tela_operacao('relatorios','dashboard_bens','Bens do indicador',status=422 if erros else 200,
        filtros=filtros,erros=erros,voltar_dashboard=url_for('relatorios',**links_dashboard(filtros)),
        link_exportar=url_for('exportar_dashboard',**links_dashboard(filtros)),**paginar_operacao(consulta.order_by(Bem.nome,Bem.id)))


@app.get('/relatorios/dashboard.csv')
@login_obrigatorio
def exportar_dashboard():
    consulta, filtros, erros, _ = consulta_dashboard()
    if erros:
        return Response(' '.join(erros), status=422, mimetype='text/plain')

    @stream_with_context
    def gerar():
        yield '\ufeff'
        out = io.StringIO()
        writer = csv.writer(out, delimiter=';', lineterminator='\r\n')
        writer.writerow(
            [
                'Bem',
                'Identificação',
                'Categoria',
                'Convênio',
                'Local',
                'Responsável',
                'Situação',
                'Data de aquisição',
                'Valor de aquisição (R$)',
                'Nota fiscal',
                'Fornecedor',
                'Forma de entrada',
                'Doador / processo de origem',
                'Conferência válida',
            ]
        )
        yield out.getvalue()
        out.seek(0)
        out.truncate(0)
        for b in db.session.scalars(consulta.order_by(Bem.id).execution_options(yield_per=200)):
            linha = [
                b.nome,
                b.patrimonio,
                b.categoria or 'Sem categoria',
                b.convenio,
                b.local,
                b.responsavel,
                'Baixado' if b.encerrado else b.situacao,
                datahora(b.data_aquisicao),
                str(b.valor).replace('.', ',') if b.valor is not None else 'Não informado',
                b.nota_fiscal or ('Arquivo anexado' if b.nota_fiscal_anexada else 'Não informada'),
                b.fornecedor,
                b.forma_ingresso or 'Compra',
                b.ingresso_detalhe,
                'Sim' if b.conferido else 'Não',
            ]
            writer.writerow(
                [
                    (
                        ("'" + str(v))
                        if str(v).lstrip().startswith(('=', '+', '-', '@'))
                        or str(v).startswith(('\n', '\r', '\t'))
                        else str(v)
                    )
                    for v in linha
                ]
            )
            yield out.getvalue()
            out.seek(0)
            out.truncate(0)

    return Response(
        gerar(),
        content_type='text/csv; charset=utf-8',
        headers={
            'Content-Disposition': f'attachment; filename=patrimonio_filtrado_{hoje_local()}.csv'
        },
    )

app.jinja_loader=ChoiceLoader([DictLoader({'coordenacoes_cadastro':COORDENACOES_TEMPLATE,'categorias_cadastro':CATEGORIAS_TEMPLATE,'dashboard_relatorios':DASHBOARD_RELATORIOS_TEMPLATE,'dashboard_bens':DASHBOARD_BENS_TEMPLATE}),app.jinja_loader])


def painel_inventario(campanha=None):
    if campanha:return redirect(url_for('inventario_detalhe',inventario_id=campanha.id,**filtros_retorno_inventario()))
    return tela_operacao('inventario','inv_vazio','Inventário')

INVENTARIO_RELATORIO=r'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Relação de bens · {{ inv.nome }}</title><style>
*{box-sizing:border-box}body{font:12px Arial,sans-serif;color:#182b23;margin:24px}h1{font-size:21px;margin:6px 0}h2{font-size:15px}p{line-height:1.6}.toolbar{display:flex;gap:12px;align-items:center;margin-bottom:24px}.toolbar button,.toolbar a{padding:12px 18px;background:#19543d;color:white;border:0;border-radius:6px;text-decoration:none;cursor:pointer}table{width:100%;border-collapse:collapse;table-layout:fixed}th,td{border:1px solid #b9c8bf;padding:7px;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#edf2ee;font-size:10px}td{font-size:10px}small{display:block;margin-top:5px}.summary{padding:10px;background:#f1f5f2;margin:15px 0}.footer{font-size:10px;margin-top:16px}@page{size:A4 landscape;margin:12mm}@media print{body{margin:0}.toolbar{display:none}thead{display:table-header-group}tr{break-inside:avoid}th{print-color-adjust:exact}a{color:inherit}.footer{position:static}}
</style></head><body><div class="toolbar"><a href="{{ voltar }}">Voltar à lista</a><button onclick="window.print()">Imprimir / salvar em PDF</button><span>Na impressão, escolha “Salvar como PDF”. Ative cabeçalhos e rodapés do navegador para numerar as páginas.</span></div><header><strong>ICMBio · NGI Carajás</strong><h1>Inventário — relação de bens</h1><h2>{{ inv.nome }}</h2><p>Base / local: {{ local_filtro or 'Todos os locais da campanha' }} · Resultado: {{ filtro or 'Todos' }}<br>Busca: {{ q or 'Sem restrição' }} · Emissão: {{ emitido|datahora }}<br>Campanha INV-{{ '%06d'|format(inv.id) }} · {{ inv.status }}</p></header><div class="summary"><strong>{{ total }} bens nesta seleção</strong> · Verificados: {{ total-resumo.get('Pendente',0) }} · Pendentes: {{ resumo.get('Pendente',0) }} · Divergências: {{ resumo.get('Divergência',0) }} · Não localizados: {{ resumo.get('Não localizado',0) }}</div><table><thead><tr><th style="width:4%">Item</th><th style="width:12%">Patrimônio</th><th style="width:19%">Bem / marca / modelo</th><th style="width:12%">Número de série</th><th style="width:17%">Base / ambiente</th><th style="width:14%">Responsável</th><th style="width:10%">Resultado</th><th style="width:12%">Observações</th></tr></thead><tbody>{% for item in rows %}<tr><td>{{ loop.index }}</td><td>{{ item.retrato.numero_ngi or item.retrato.plaqueta_original or 'Sem plaqueta' }}</td><td><strong>{{ item.retrato.nome }}</strong><small>{{ item.retrato.marca or '' }} / {{ item.retrato.modelo or '' }}</small></td><td>{{ item.retrato.serie or 'Não informado' }}</td><td>{{ item.retrato.local }}<small>{{ item.retrato.complemento or '' }}</small></td><td>{{ item.retrato.responsavel or 'Não informado' }}</td><td>{{ item.status }}</td><td>{{ item.observacao or '—' }}</td></tr>{% else %}<tr><td colspan="8">Nenhum bem encontrado com estes filtros.</td></tr>{% endfor %}</tbody></table><p class="footer">Dados dos bens registrados na abertura da campanha. Resultados de conferência atualizados na emissão. Este relatório não altera o cadastro nem substitui termos de responsabilidade.</p></body></html>'''
OP_TEMPLATES['inv_imprimir']=INVENTARIO_RELATORIO
OP_TEMPLATES['inv_vazio']='''<div class="list-heading"><div><h1>Inventário</h1><p>Confira os bens de cada base e registre o que encontrou.</p></div></div><section class="panel"><h2>Nenhuma campanha iniciada</h2><p>Abra uma campanha para selecionar os bens que serão conferidos.</p>{% if not usuario.leitura %}<a class="btn primary" href="{{ url_for('inventario',aba='cadastro') }}">Iniciar inventário</a>{% endif %}</section>'''
app.jinja_loader=ChoiceLoader([DictLoader(OP_TEMPLATES),app.jinja_loader])


# ============================================================
# PLAQUETAS EM LOTE: escopo no servidor, numeração transacional, PDF real
# ============================================================
ESTADOS_ETIQUETA=('Não verificada','Sem etiqueta','Danificada','Legível')


def consulta_plaquetas():
    fonte = request.form if request.method == 'POST' else request.args
    local = fonte.get('local', '').strip()[:160]
    estado = fonte.get('estado', '')
    q = fonte.get('q', '').strip()[:120]
    consulta = select(Bem).where(Bem.encerrado.is_(False))
    if local:
        consulta = consulta.where(Bem.local == local)
    if estado == 'sem_numero':
        consulta = consulta.where(
            or_(Bem.numero_ngi.is_(None), Bem.numero_ngi == ''),
            or_(Bem.plaqueta_original.is_(None), Bem.plaqueta_original == ''),
        )
    elif estado == 'sem_ngi':
        consulta = consulta.where(or_(Bem.numero_ngi.is_(None), Bem.numero_ngi == ''))
    elif estado in ESTADOS_ETIQUETA:
        consulta = consulta.where(Bem.etiqueta_situacao == estado)
    if q:
        consulta = consulta.where(
            or_(
                *(
                    c.icontains(q, autoescape=True)
                    for c in (Bem.nome, Bem.serie, Bem.numero_ngi, Bem.plaqueta_original)
                )
            )
        )
    return consulta, dict(local=local, estado=estado, q=q)


# Cores da plaqueta em CMYK (padrão de gráfica). QR Code e número em 100% preto (K),
# que é a cor mais nítida e fácil de ler pelo celular, sem risco de registro entre tintas.
CMYK_VERDE_ESCURO = (1.00, 0.30, 1.00, 0.50)
CMYK_VERDE = (0.80, 0.20, 0.85, 0.20)
CMYK_LIMAO = (0.40, 0.00, 1.00, 0.00)
CMYK_PRETO = (0, 0, 0, 1)


@lru_cache(maxsize=1)
def logo_plaqueta_alta():
    """Logo do ICMBio para a plaqueta: versão reduzida (mapa + ICMBio), sem as
    linhas pequenas de baixo, que ficariam ilegíveis em 4 mm. Achatada em
    fundo branco, em alta resolução (~1400 dpi). Fica em RGB de propósito: o
    sistema de impressão da gráfica converte com o perfil de cor dela, mais fiel que uma conversão simples."""
    imagem = Image.open(io.BytesIO(bytes_identidade_visual('icmbio'))).convert('RGBA')
    largura, altura = imagem.size
    imagem = imagem.crop((0, 0, largura, int(altura * 0.825)))
    caixa = imagem.getchannel('A').getbbox()
    if caixa:
        imagem = imagem.crop(caixa)
    fundo = Image.new('RGBA', imagem.size, (255, 255, 255, 255))
    fundo.alpha_composite(imagem)
    imagem = fundo.convert('RGB')
    alvo = 320
    if imagem.height > alvo:
        imagem = imagem.resize((round(imagem.width * alvo / imagem.height), alvo), Image.LANCZOS)
    return imagem


def pdf_plaquetas(bens, grafica=False):
    """Plaquetas de 40 x 25 mm em A4.
    Escritório: 36 por página (4 x 9), cantos arredondados e linha de corte.
    Gráfica: 32 por página (4 x 8), sangria de 2 mm, marcas de corte fora da
    arte, cores CMYK e logo/QR em alta definição (tudo vetorial, exceto a logo)."""
    from reportlab.lib.utils import ImageReader
    out = io.BytesIO()
    c = pdf_canvas.Canvas(out, pagesize=A4, pageCompression=1)
    c.setTitle('Plaquetas patrimoniais - NGI ICMBio Carajás' + (' (gráfica)' if grafica else ''))
    c.setAuthor('NGI ICMBio Carajás')
    c.setViewerPreference('PrintScaling', 'None')
    w, h = 40 * mm, 25 * mm
    sangria = 2 * mm if grafica else 0
    if grafica:
        colunas, linhas, passo_x, passo_y, x0, y_topo = 4, 8, 46 * mm, 31 * mm, 15 * mm, 272 * mm
    else:
        colunas, linhas, passo_x, passo_y, x0, y_topo = 4, 9, 45 * mm, 28 * mm, 17.5 * mm, 272 * mm
    por_pagina = colunas * linhas
    paginas = (len(bens) + por_pagina - 1) // por_pagina
    try:
        logo_et = ImageReader(logo_plaqueta_alta())
        logo_proporcao = logo_plaqueta_alta().width / logo_plaqueta_alta().height
    except (OSError, ValueError, UnidentifiedImageError):
        logo_et, logo_proporcao = None, 1

    def texto(valor, x, y, maximo, tamanho=6, fonte='NGI-Bold', minimo=4.5):
        valor = str(valor)
        while tamanho > minimo and stringWidth(valor, fonte, tamanho) > maximo:
            tamanho -= 0.1
        if stringWidth(valor, fonte, tamanho) > maximo:
            raise ValueError(
                'Uma identificação é longa demais para 40 × 25 mm. Revise o número ou solicite um gabarito maior; nenhum código foi cortado.'
            )
        c.setFont(fonte, tamanho)
        c.drawString(x, y, valor)

    def marcas_de_corte(x, y):
        # Fora da sangria, 0,25 pt em preto 100% (registro), sem tocar na arte.
        c.setStrokeColorCMYK(*CMYK_PRETO)
        c.setLineWidth(0.25)
        afasta = sangria + 0.6 * mm
        comp = 1.2 * mm
        for px in (x, x + w):
            for py, sentido in ((y, -1), (y + h, 1)):
                c.line(px, py + sentido * afasta, px, py + sentido * (afasta + comp))
        for py in (y, y + h):
            for px, sentido in ((x, -1), (x + w, 1)):
                c.line(px + sentido * afasta, py, px + sentido * (afasta + comp), py)

    emitido = datetime.now(timezone(timedelta(hours=-3))).strftime('%d/%m/%Y às %H:%M')
    for inicio in range(0, len(bens), por_pagina):
        pagina_atual = inicio // por_pagina + 1
        qtd_pagina = len(bens[inicio: inicio + por_pagina])
        # ---- cabeçalho da folha: logo, título e dados da impressão (pouca tinta)
        if logo_et is not None:
            c.drawImage(logo_et, 15 * mm, 279.5 * mm, 13 * mm * logo_proporcao, 13 * mm, preserveAspectRatio=True, anchor='sw')
        sep_x = 15 * mm + 13 * mm * logo_proporcao + 4 * mm
        c.setStrokeColorCMYK(0, 0, 0, 0.18); c.setLineWidth(0.5)
        c.line(sep_x, 280 * mm, sep_x, 292.5 * mm)
        c.setFillColorCMYK(*CMYK_VERDE_ESCURO)
        c.setFont('NGI-Bold', 15)
        c.drawString(sep_x + 4 * mm, 286.6 * mm, 'Plaquetas patrimoniais')
        c.setFillColorCMYK(*CMYK_VERDE)
        c.setFont('NGI', 8.2)
        c.drawString(sep_x + 4 * mm, 281.6 * mm, 'NGI ICMBio Carajás · Patrimônio Carajás')
        c.setFillColorCMYK(*CMYK_VERDE_ESCURO)
        c.setFont('NGI-Bold', 9)
        c.drawRightString(195 * mm, 289.4 * mm, f'{qtd_pagina} plaqueta(s) · folha {pagina_atual} de {paginas}')
        c.setFillColorCMYK(0, 0, 0, 0.6)
        c.setFont('NGI', 7.4)
        c.drawRightString(195 * mm, 285.4 * mm, f'Emitido em {emitido}')
        c.drawRightString(195 * mm, 281.6 * mm, 'Arquivo para gráfica · sangria 2 mm · cores CMYK' if grafica
                          else 'Impressora comum · etiquetas de 4 × 2,5 cm')
        for ini_f, fim_f, cor in ((0, 0.70, CMYK_VERDE_ESCURO), (0.70, 0.88, CMYK_VERDE), (0.88, 1.0, CMYK_LIMAO)):
            c.setFillColorCMYK(*cor)
            c.rect(15 * mm + 180 * mm * ini_f, 276.6 * mm, 180 * mm * (fim_f - ini_f), 1.1 * mm, fill=1, stroke=0)
        for i, bem in enumerate(bens[inicio: inicio + por_pagina]):
            x = x0 + (i % colunas) * passo_x
            y = y_topo - h - (i // colunas) * passo_y
            topo = 7.0 * mm
            faixa = 0.9 * mm
            # Fundo branco + faixas (na gráfica, as faixas avançam 2 mm além do corte)
            if grafica:
                c.setFillColorCMYK(0, 0, 0, 0)
                c.rect(x - sangria, y - sangria, w + 2 * sangria, h + 2 * sangria, fill=1, stroke=0)
                c.setFillColorCMYK(*CMYK_VERDE_ESCURO)
                c.rect(x - sangria, y + h - topo, w + 2 * sangria, topo + sangria, fill=1, stroke=0)
                ini_x, larg_total, base_y, alt_faixa = x - sangria, w + 2 * sangria, y - sangria, faixa + sangria
            else:
                c.setFillColorCMYK(0, 0, 0, 0)
                c.setStrokeColorCMYK(0, 0, 0, 0.30)
                c.setLineWidth(0.25)
                c.roundRect(x, y, w, h, 1.2 * mm, fill=1, stroke=1)
                c.saveState()
                contorno = c.beginPath()
                contorno.roundRect(x, y, w, h, 1.2 * mm)
                c.clipPath(contorno, stroke=0, fill=0)
                c.setFillColorCMYK(*CMYK_VERDE_ESCURO)
                c.rect(x, y + h - topo, w, topo, fill=1, stroke=0)
                ini_x, larg_total, base_y, alt_faixa = x, w, y, faixa
            for ini_f, fim_f, cor in ((0, 0.70, CMYK_VERDE_ESCURO), (0.70, 0.88, CMYK_VERDE), (0.88, 1.0, CMYK_LIMAO)):
                c.setFillColorCMYK(*cor)
                c.rect(ini_x + larg_total * ini_f, base_y, larg_total * (fim_f - ini_f) + 0.05 * mm, alt_faixa, fill=1, stroke=0)
            if not grafica:
                c.restoreState()
            # Logo do ICMBio em caixa branca, maior e nítida
            alt_logo = topo - 1.3 * mm
            larg_logo = alt_logo * logo_proporcao
            c.setFillColorCMYK(0, 0, 0, 0)
            c.roundRect(x + 1.0 * mm, y + h - topo + 0.55 * mm, larg_logo + 0.9 * mm, topo - 1.1 * mm, 0.6 * mm, fill=1, stroke=0)
            if logo_et is not None:
                c.drawImage(logo_et, x + 1.45 * mm, y + h - topo + 0.65 * mm, larg_logo, alt_logo,
                            preserveAspectRatio=True, anchor='c')
            nome_x = x + 1.0 * mm + larg_logo + 0.9 * mm + 1.2 * mm
            c.setFillColorCMYK(0, 0, 0, 0)
            texto('NGI ICMBio Carajás', nome_x, y + h - topo + 2.45 * mm, x + w - 0.9 * mm - nome_x, 8.4, minimo=6)
            # QR Code vetorial, 100% preto, com margem branca de 2 módulos
            qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2)
            qr.add_data(PUBLIC_URL + url_for('ficha', bem_id=bem.id))
            qr.make(fit=True)
            matriz = qr.get_matrix()
            lado = h - topo - faixa - 0.5 * mm
            modulo = lado / len(matriz)
            qx = x + 0.6 * mm
            qy = y + faixa + 0.25 * mm
            c.setFillColorCMYK(*CMYK_PRETO)
            path = c.beginPath()
            for lin, vetor in enumerate(matriz):
                inicio_run = None
                for col, escuro in enumerate(list(vetor) + [False]):
                    # módulos vizinhos viram um retângulo só: sem frestas brancas na impressão
                    if escuro and inicio_run is None:
                        inicio_run = col
                    elif not escuro and inicio_run is not None:
                        path.rect(qx + inicio_run * modulo, qy + (len(matriz) - lin - 1) * modulo,
                                  (col - inicio_run) * modulo, modulo * 1.002)
                        inicio_run = None
            c.drawPath(path, fill=1, stroke=0)
            tx = qx + lado + 0.9 * mm
            maximo = x + w - 1.0 * mm - tx
            c.setFillColorCMYK(*CMYK_VERDE)
            texto('PATRIMÔNIO', tx, y + 12.6 * mm, maximo, 6.6)
            codigo = bem.numero_ngi or bem.plaqueta_original
            c.setFillColorCMYK(*CMYK_PRETO)
            tamanho = 19.0
            while tamanho > 9 and stringWidth(codigo, 'NGI-Bold', tamanho) > maximo:
                tamanho -= 0.1
            if stringWidth(codigo, 'NGI-Bold', tamanho) <= maximo:
                texto(codigo, tx, y + 6.0 * mm, maximo, tamanho)
            else:
                corte = codigo.rfind('-') + 1 if '-' in codigo[1:] else (len(codigo) + 1) // 2
                for n, parte in enumerate((codigo[:corte], codigo[corte:])):
                    texto(parte, tx, y + (8.4 - n * 3.6) * mm, maximo, 9.5)
            c.setFillColorCMYK(*CMYK_VERDE_ESCURO)
            texto('Patrimônio Carajás', tx, y + 2.1 * mm, maximo, 5.2, fonte='NGI', minimo=4.6)
            marcas_de_corte(x, y)
        # ---- rodapé: três passos para a impressão sair certa
        c.setFillColorCMYK(0.06, 0, 0.10, 0)
        c.setStrokeColorCMYK(0.12, 0, 0.20, 0.05); c.setLineWidth(0.4)
        c.roundRect(15 * mm, 8.5 * mm, 180 * mm, 9 * mm, 2 * mm, fill=1, stroke=1)
        passos_folha = (('Cortar nas marcas', 'a arte avança 2 mm (sangria)'), ('Vinil ou poliéster fosco', 'com laminação, para durar em campo'),
                        ('Prova antes do lote', 'leia alguns QR Codes no celular')) if grafica else \
                       (('Tamanho real (100%)', 'sem "ajustar à página"'), ('Recorte nas marcas', 'cada etiqueta tem 4 × 2,5 cm'),
                        ('Teste o QR Code', 'com o celular, antes de colar'))
        for n, (titulo, detalhe) in enumerate(passos_folha):
            px = 18 * mm + n * 60 * mm
            c.setFillColorCMYK(*CMYK_VERDE_ESCURO)
            c.circle(px + 2.4 * mm, 13 * mm, 2.4 * mm, fill=1, stroke=0)
            c.setFillColorCMYK(0, 0, 0, 0)
            c.setFont('NGI-Bold', 7.5)
            c.drawCentredString(px + 2.4 * mm, 12.15 * mm, str(n + 1))
            c.setFillColorCMYK(*CMYK_VERDE_ESCURO)
            c.setFont('NGI-Bold', 7.6)
            c.drawString(px + 6.6 * mm, 13.9 * mm, titulo)
            c.setFillColorCMYK(0, 0, 0, 0.6)
            c.setFont('NGI', 6.6)
            c.drawString(px + 6.6 * mm, 10.9 * mm, detalhe)
        c.setFillColorCMYK(0, 0, 0, 0.5)
        c.setFont('NGI', 6.6)
        c.drawString(15 * mm, 4.5 * mm, 'Patrimônio Carajás · O QR Code abre a ficha do bem e a conferência do inventário.')
        c.drawRightString(195 * mm, 4.5 * mm, f'Folha {pagina_atual} de {paginas}')
        c.showPage()
    c.save()
    nome = 'plaquetas_ngi_carajas_grafica.pdf' if grafica else 'plaquetas_ngi_carajas.pdf'
    return Response(
        out.getvalue(),
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="{nome}"'},
    )


@app.get('/bem/<int:bem_id>/plaqueta.pdf')
@login_obrigatorio
def plaqueta_pdf_individual(bem_id):
    bem = carregar(Bem, bem_id)
    if not (bem.plaqueta_original or bem.numero_ngi):
        abort(400, description='Bem sem identificação patrimonial.')
    try:
        return pdf_plaquetas([bem], grafica=request.args.get('grafica') == '1')
    except ValueError as e:
        flash(str(e))
        return redirect(url_for('ficha', bem_id=bem.id))


@app.route('/plaquetas', methods=['GET', 'POST'])
@login_obrigatorio
def plaquetas_lote():
    consulta, filtros = consulta_plaquetas()
    retorno = url_for('plaquetas_lote', **filtros)
    if request.method == 'POST':
        try:
            if request.form.get('todos') != 'sim':
                ids = request.form.getlist('bens')
                if not ids or len(ids) > 25 or any(not v.isdecimal() for v in ids):
                    raise ValueError(
                        'Selecione os bens desta página ou marque todos os resultados do filtro.'
                    )
                consulta = consulta.where(Bem.id.in_([int(v) for v in ids]))
            acao = request.form.get('acao', '')
            if acao not in (
                'pdf',
                'pdf_grafica',
                'gerar',
                'Sem etiqueta',
                'Danificada',
                'Legível',
                'Não verificada',
            ):
                abort(400)
            if acao not in ('pdf', 'pdf_grafica'):
                repetida = validar_token_operacao()
                if repetida is not None:
                    return repetida
            bens = db.session.scalars(
                consulta.order_by(Bem.id).with_for_update()
                if acao not in ('pdf', 'pdf_grafica')
                else consulta.order_by(Bem.id)
            ).all()
            if not bens:
                raise ValueError('Nenhum bem ativo corresponde à seleção.')
            if acao in ('pdf', 'pdf_grafica'):
                faltantes = sum(not (b.numero_ngi or b.plaqueta_original) for b in bens)
                if faltantes:
                    raise ValueError(
                        f'{faltantes} bem(ns) ainda sem número. Gere a identificação antes de imprimir. Os números existentes serão preservados.'
                    )
                return pdf_plaquetas(bens, grafica=acao == 'pdf_grafica')
            alterados = 0
            if acao == 'gerar':
                travar_numeracao()
                proximo = maior_numero_patrimonio() + 1
                for bem in bens:
                    if bem.numero_ngi:
                        continue
                    antes = snapshot(bem)
                    do_antigo = numero_de_plaqueta(bem.plaqueta_original)
                    if do_antigo and not numero_ocupado(do_antigo, bem.id):
                        bem.numero_ngi = do_antigo
                    else:
                        while numero_ocupado(formatar_patrimonio(proximo)):
                            proximo += 1
                        bem.numero_ngi = formatar_patrimonio(proximo)
                        proximo += 1
                    db.session.flush()
                    bem.revisao += 1
                    bem.conferido = False
                    bem.atualizado_em = datetime.now(timezone.utc)
                    registrar_evento(bem, 'Número de patrimônio definido (lote)', antes)
                    alterados += 1
            else:
                for bem in bens:
                    if bem.etiqueta_situacao == acao:
                        continue
                    antes = snapshot(bem)
                    bem.etiqueta_situacao = acao
                    bem.revisao += 1
                    bem.conferido = False
                    bem.atualizado_em = datetime.now(timezone.utc)
                    registrar_evento(bem, 'Atualização da etiqueta física', antes)
                    alterados += 1
            if acao == 'gerar':
                flash(
                    f'{alterados} número(s) de patrimônio definido(s); {len(bens)-alterados} já tinham número e foram mantidos.'
                )
            else:
                flash(
                    f'{alterados} bem(ns) atualizado(s). A impressão não marca a etiqueta como fixada.'
                )
            if acao == 'gerar' and filtros['estado'] in ('sem_numero', 'sem_ngi'):
                filtros['estado'] = ''
                retorno = url_for('plaquetas_lote', **filtros)
                flash(
                    'O filtro sem número foi limpo para permitir selecionar e imprimir os bens identificados.'
                )
            return finalizar_operacao(retorno)
        except ValueError as e:
            db.session.rollback()
            flash(str(e))
            return redirect(retorno)
    locais = db.session.scalars(
        select(Bem.local).where(Bem.encerrado.is_(False)).distinct().order_by(Bem.local)
    ).all()
    return tela_operacao(
        'bens',
        'plaquetas_lote',
        'Plaquetas patrimoniais',
        filtros=filtros,
        locais_plaquetas=locais,
        estados_etiqueta=ESTADOS_ETIQUETA,
        operacao_token=token_operacao(),
        numeracao_pendente=db.session.scalar(select(func.count()).select_from(bens_numeracao_pendente().subquery())) or 0,
        **paginar_operacao(consulta.order_by(Bem.id)),
    )

def bens_numeracao_pendente():
    return select(Bem).where(Bem.encerrado.is_(False), or_(
        Bem.numero_ngi.like('NGI-%'),
        and_(Bem.numero_ngi.is_(None), Bem.plaqueta_original.is_not(None), Bem.plaqueta_original != '')))


@app.post('/plaquetas/atualizar-numeracao')
@login_obrigatorio
def atualizar_numeracao():
    if g.usuario.leitura:
        abort(403)
    repetida = validar_token_operacao()
    if repetida is not None:
        return repetida
    travar_numeracao()
    pendentes = db.session.scalars(bens_numeracao_pendente().order_by(Bem.id).with_for_update()).all()
    convertidos, conflitos = 0, []
    # 1º os bens com plaqueta antiga: o número sai da própria plaqueta (PA 010 -> 0010)
    sem_numero = []
    for bem in pendentes:
        alvo = numero_de_plaqueta(bem.plaqueta_original)
        if not alvo:
            sem_numero.append(bem)
            continue
        if bem.numero_ngi == alvo:
            continue
        if numero_ocupado(alvo, bem.id):
            conflitos.append(f'{bem.nome} ({bem.plaqueta_original})')
            continue
        antes = snapshot(bem)
        bem.numero_ngi = alvo
        db.session.flush()
        bem.revisao += 1
        bem.atualizado_em = datetime.now(timezone.utc)
        registrar_evento(bem, 'Numeração atualizada para a sequência', antes)
        convertidos += 1
    # 2º os que só tinham código NGI-ano: próximo número depois do maior
    proximo = maior_numero_patrimonio() + 1
    for bem in sem_numero:
        if not (bem.numero_ngi or '').startswith('NGI-'):
            conflitos.append(f'{bem.nome} (plaqueta "{bem.plaqueta_original}" sem algarismos)')
            continue
        while numero_ocupado(formatar_patrimonio(proximo)):
            proximo += 1
        antes = snapshot(bem)
        bem.numero_ngi = formatar_patrimonio(proximo)
        proximo += 1
        db.session.flush()
        bem.revisao += 1
        bem.atualizado_em = datetime.now(timezone.utc)
        registrar_evento(bem, 'Numeração atualizada para a sequência', antes)
        convertidos += 1
    resposta = finalizar_operacao(url_for('plaquetas_lote'))
    flash(f'{convertidos} bem(ns) passaram para a numeração única de patrimônio.')
    if conflitos:
        flash('Confira manualmente (número repetido ou plaqueta sem algarismos): ' + '; '.join(conflitos[:15])
              + (f' e mais {len(conflitos) - 15}.' if len(conflitos) > 15 else '.'))
    return resposta


OP_TEMPLATES['inv_link_campo']=r'''<a class="back" href="{{ url_for('inventario_detalhe',inventario_id=inv.id) }}#equipe-campo">← Inventário {{ inv.nome }}</a><div class="list-heading"><div><h1>Link da equipe de campo</h1><p>{{ link.rotulo or 'Equipe de campo' }} · {{ link.local or 'Todos os locais' }} · válido até {{ link.expira_data|datahora }}</p></div></div>
<section class="panel campo-gerado"><div class="campo-gerado-qr"><img src="{{ qr_link }}" alt="QR Code do link da equipe" width="220" height="220"><small>A pessoa também pode apontar a câmera para este QR Code.</small></div><div class="campo-gerado-texto"><label for="campo-url">Link para enviar à equipe</label><div class="campo-copiar"><input id="campo-url" readonly value="{{ link_url }}"><button type="button" class="btn" id="campo-copiar">Copiar</button></div><a class="btn primary campo-whats" href="{{ whatsapp }}" target="_blank" rel="noopener">Enviar pelo WhatsApp</a>
<ol class="campo-passos"><li><strong>Antes de sair, com internet:</strong> cada pessoa abre o link uma vez e digita o nome. A lista de bens fica guardada no celular.</li><li><strong>No campo, mesmo sem sinal:</strong> abre o mesmo link (pode adicionar à tela inicial), aponta a câmera para a plaqueta e toca em “Está tudo certo” ou “Tem algo diferente”.</li><li><strong>Na volta:</strong> quando o celular pegar internet, as conferências são enviadas sozinhas e aparecem neste inventário.</li></ol>
<p class="hint">Guarde este link: por segurança ele é mostrado só agora. Se perder, gere outro e desative este.</p></div></section>
<script>document.getElementById('campo-copiar').addEventListener('click',async()=>{const c=document.getElementById('campo-url');try{await navigator.clipboard.writeText(c.value);}catch(e){c.select();document.execCommand('copy');}document.getElementById('campo-copiar').textContent='Copiado';});</script>'''


OP_TEMPLATES['indicadores']=r'''
{% macro indicador(t) %}<article class="ind-card ind-{{ t.classe }}" id="ind-{{ t.chave }}">
<header class="ind-head"><h3>{{ t.nome }}</h3><span class="ind-band">{{ t.faixa }}</span></header>
<div class="ind-value"><strong>{{ t.valor }}</strong><span>{{ t.detalhe }}</span></div>
{% if t.barra is not none %}<div class="ind-meter" aria-hidden="true"><span style="width:{{ t.barra }}%"></span></div>{% endif %}
<p class="ind-resumo">{{ t.mede }}</p>
{% if t.exemplo %}<p class="ind-exemplo"><b>Exemplo:</b> {{ t.exemplo }}</p>{% endif %}
<details class="ind-como"><summary>Como é calculado?</summary><dl class="ind-explain">
<div><dt>Como calcula</dt><dd><code>{{ t.formula }}</code></dd></div>
<div class="destaque"><dt>Neste recorte</dt><dd>{{ t.calculo }}</dd></div>
<div><dt>Referência</dt><dd>{{ t.referencia }}</dd></div>
</dl></details>
{% if t.link %}<a class="text-action ind-link" href="{{ t.link }}">{{ t.link_rotulo }} →</a>{% endif %}
{% if t.bens %}<details class="ind-bens"><summary>Ver {{ 'os ' ~ t.bens|length ~ ' bens' if t.bens|length > 1 else 'o bem' }}{{ ' (primeiros 100)' if t.bens|length >= 100 }}</summary><ul>{% for b in t.bens %}<li><a href="{{ url_for('ficha', bem_id=b.id) }}">{{ b.nome }}</a><small>{{ b.patrimonio }} · {{ b.local }} · {{ b.situacao }}{% if b.dias is not none %} · {{ b.dias }} dias{% endif %}</small></li>{% endfor %}</ul></details>{% endif %}
</article>{% endmacro %}
<div class="list-heading"><div><h1>Indicadores de gestão</h1><p>O resultado de cada indicador em um cartão, com um exemplo. Clique em “Como é calculado?” para ver a fórmula e a base legal.</p></div><div class="pdf-btns"><a class="btn" href="{{ link_csv }}">Exportar CSV</a><a class="btn primary" href="{{ link_csv|replace('/relatorios/indicadores.csv','/relatorios/indicadores.pdf') }}">Baixar PDF</a></div></div><nav class="registry-navigation" aria-label="Relatórios"><a href="{{ url_for('relatorios') }}" class="{{ 'current' if request.endpoint=='relatorios' }}">Dashboard patrimonial</a><a href="{{ url_for('indicadores_gestao') }}" class="{{ 'current' if request.endpoint=='indicadores_gestao' }}">Indicadores de gestão</a><a href="{{ url_for('relatorio_operacional') }}" class="{{ 'current' if request.endpoint=='relatorio_operacional' }}">Relatório de registros</a></nav>
<section class="panel analytics-filters"><form method="get" action="{{ url_for('indicadores_gestao') }}"><div class="analytics-filter-grid">
<div class="field"><label for="ind-convenio">Convênio</label><select id="ind-convenio" name="convenio_id"><option value="">Todos</option>{% for c in convenios_ind %}<option value="{{ c.id }}" {{ 'selected' if filtros.convenio_id==c.id }}>{{ c.nome }}</option>{% endfor %}</select></div>
<div class="field"><label for="ind-base">Base / local</label><select id="ind-base" name="base_id"><option value="">Todas</option>{% for b in bases_ind %}<option value="{{ b.id }}" {{ 'selected' if filtros.base_id==b.id }}>{{ b.nome }}</option>{% endfor %}</select></div>
<div class="field"><label for="ind-inv">Inventário analisado</label><select id="ind-inv" name="inventario_id">{% for c in campanhas %}<option value="{{ c.id }}" {{ 'selected' if campanha and campanha.id==c.id }}>INV-{{ '%06d'|format(c.id) }} · {{ c.nome }} ({{ c.status|lower }})</option>{% else %}<option value="">Nenhum inventário registrado</option>{% endfor %}</select></div>
<div class="field"><label for="ind-dias">Bem parado há mais de</label><select id="ind-dias" name="dias">{% for d in [90,180,365] %}<option value="{{ d }}" {{ 'selected' if filtros.dias==d }}>{{ d }} dias</option>{% endfor %}</select></div>
</div><div class="analytics-filter-bottom"><button class="btn primary">Aplicar filtros</button><a class="btn" href="{{ url_for('indicadores_gestao') }}">Limpar filtros</a></div>
<p class="hint ind-nota">As cores são faixas de leitura rápida adotadas pelo NGI (<span class="ind-chip ok">Bom</span> <span class="ind-chip warn">Atenção</span> <span class="ind-chip bad">Crítico</span>). Não são metas legais. Os indicadores apontam onde olhar; a decisão sobre cada bem continua com o patrimônio e a comissão.</p></form></section>

<section class="ind-section"><div class="ind-section-head"><span>1</span><div><h2>Inventário</h2><p>{% if campanha %}INV-{{ '%06d'|format(campanha.id) }} · {{ campanha.nome }} · {{ campanha.local }} · {{ campanha.status }}{% if campanha.encerrado_em %} em {{ campanha.encerrado_em|datahora }}{% endif %}{% if filtros.convenio_id %} · somente bens do convênio filtrado{% endif %}{% else %}Abra um inventário para medir a acurácia do controle.{% endif %}</p></div></div>
{% if campanha %}<div class="ind-grid">{% for t in ind_inventario %}{{ indicador(t) }}{% endfor %}</div>
{% if historico %}<div class="panel ind-historico"><h3>Evolução entre inventários</h3><p class="hint">Compare as campanhas para ver se o controle está melhorando.</p><div class="tablewrap"><table><thead><tr><th>Inventário</th><th>Situação</th><th>Bens</th><th>Acurácia</th><th>Não localizados</th><th>Divergências</th></tr></thead><tbody>{% for h in historico %}<tr><td><a class="text-action" href="{{ url_for('inventario_detalhe', inventario_id=h.id) }}">INV-{{ '%06d'|format(h.id) }}</a><small class="table-sub">{{ h.nome }} · {{ h.local }}</small></td><td>{{ h.status }}{% if h.data %}<small class="table-sub">{{ h.data|datahora }}</small>{% endif %}</td><td>{{ h.total }}</td><td><span class="ind-chip {{ h.classe_acuracia }}">{{ h.acuracia }}</span></td><td>{{ h.nao_localizados }}</td><td>{{ h.divergencias }}</td></tr>{% endfor %}</tbody></table></div></div>{% endif %}
{% else %}<div class="panel list-empty">Nenhum inventário registrado para este filtro. Em Inventário, abra uma campanha e confira os bens: os indicadores aparecem aqui.</div>{% endif %}</section>

<section class="ind-section"><div class="ind-section-head"><span>2</span><div><h2>Uso dos bens</h2><p>{{ total_ativos }} bens ativos no recorte. Última atividade = movimentação concluída ou conferência em inventário; sem nenhuma, vale a data do cadastro.</p></div></div>
<div class="ind-grid">{% for t in ind_uso %}{{ indicador(t) }}{% endfor %}</div></section>

<section class="ind-section"><div class="ind-section-head"><span>3</span><div><h2>Responsabilidade</h2><p>Quem responde por cada bem, com termo emitido e aceito.</p></div></div>
<div class="ind-grid">{% for t in ind_termos %}{{ indicador(t) }}{% endfor %}</div></section>
'''


OP_TEMPLATES['plaquetas_lote']=r'''
{% if numeracao_pendente and not usuario.leitura %}<section class="panel op-section" style="border-left:4px solid #a0c517"><h2>Atualizar para a numeração única</h2><p class="hint">{{ numeracao_pendente }} bem(ns) ainda estão no formato antigo (PA 010, NGI-2026-00001…). Clique uma vez para passar todos para o número de 4 dígitos: a plaqueta PA 010 vira 0010 e quem não tem plaqueta recebe o próximo número da sequência. O número antigo continua guardado no histórico do bem.</p><form method="post" action="{{ url_for('atualizar_numeracao') }}"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><input type="hidden" name="operacao_token" value="{{ operacao_token }}"><button class="btn primary">Atualizar numeração</button></form></section>{% endif %}<div class="list-heading"><div><h1>Plaquetas patrimoniais</h1><p>Selecione a base, confira os bens e gere um único PDF para a gráfica.</p></div><a class="btn" href="{{ url_for('listar_bens') }}">Voltar aos bens</a></div><section class="panel"><form method="get" class="registry-toolbar"><div class="field"><label for="pl-local">Base / local</label><select id="pl-local" name="local"><option value="">Todos os locais</option>{% for l in locais_plaquetas %}<option {{ 'selected' if filtros.local==l }}>{{ l }}</option>{% endfor %}</select></div><div class="field"><label for="pl-estado">Situação da etiqueta</label><select id="pl-estado" name="estado"><option value="">Todas</option><option value="sem_numero" {{ 'selected' if filtros.estado=='sem_numero' }}>Sem qualquer identificação</option><option value="sem_ngi" {{ 'selected' if filtros.estado=='sem_ngi' }}>Sem número de patrimônio</option>{% for st in estados_etiqueta %}<option {{ 'selected' if filtros.estado==st }}>{{ st }}</option>{% endfor %}</select></div><div class="field"><label for="pl-q">Bem / série / patrimônio</label><input id="pl-q" name="q" value="{{ filtros.q }}" maxlength="120"></div><button class="btn primary">Filtrar</button></form><p class="hint">{{ quantidade_operacao }} bens encontrados. Numeração única de patrimônio com 4 dígitos: a plaqueta antiga PA 010 vira 0010, e bens sem plaqueta recebem o próximo número da sequência. Cadastros antigos começam como “Não verificada”: o sistema não presume que a etiqueta está ausente. Informe o estado após conferir o bem.</p></section>
{% if not usuario.leitura %}<form method="post"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><input type="hidden" name="operacao_token" value="{{ operacao_token }}">{% for k,v in filtros.items() %}<input type="hidden" name="{{ k }}" value="{{ v }}">{% endfor %}<section class="panel"><label class="op-check"><input type="checkbox" name="todos" value="sim"> Selecionar TODOS os {{ quantidade_operacao }} resultados deste filtro, incluindo outras páginas</label><p class="hint">Sem marcar essa opção, somente os bens selecionados na página entram no lote.</p><div class="op-actions"><button class="btn" name="acao" value="gerar">Gerar números de patrimônio que faltam</button><button class="btn primary" name="acao" value="pdf">Baixar PDF das plaquetas</button><button class="btn" name="acao" value="pdf_grafica" title="Com sangria de 2 mm, marcas de corte e cores CMYK">PDF para gráfica</button></div><details class="inv-details"><summary>Registrar situação da etiqueta física dos selecionados</summary><div class="op-actions">{% for st in estados_etiqueta %}<button class="btn" name="acao" value="{{ st }}">{{ st }}</button>{% endfor %}</div></details><div class="tablewrap plaques29-grid"><table><thead><tr><th>Selecionar</th><th>Bem</th><th>Nº de patrimônio</th><th>Base</th><th>Etiqueta física</th></tr></thead><tbody>{% for b in rows %}<tr><td><input type="checkbox" name="bens" value="{{ b.id }}" aria-label="Selecionar {{ b.nome }}"></td><td>{{ b.nome }}<small class="table-sub">{{ b.serie or 'Série não informada' }}</small></td><td><strong>{{ b.numero_ngi or 'NGI ainda não gerado' }}</strong>{% if b.plaqueta_original %}<small class="table-sub">Origem: {{ b.plaqueta_original }} · {{ b.origem or 'Não informada' }}</small>{% else %}<small class="table-sub">Sem patrimônio de origem informado</small>{% endif %}</td><td>{{ b.local }}</td><td>{{ b.etiqueta_situacao }}</td></tr>{% else %}<tr><td colspan="5">Nenhum bem encontrado.</td></tr>{% endfor %}</tbody></table></div>{% include 'op_paginacao' %}</section></form>{% else %}<p class="hint">A geração em lote está disponível para administradores e operadores. Seu perfil permite consulta e impressão individual pela ficha.</p>{% endif %}
<section class="panel"><h2>Como enviar para a gráfica</h2><p>O PDF contém 36 plaquetas por página A4, de 40 × 25 mm, com QR Code vetorial e marcas de corte. Envie o PDF completo à gráfica e combine o material e o adesivo. Peça impressão em escala 100%, sem ajuste à página. Valide uma amostra antes de produzir o lote.</p><p class="hint">O sistema preserva a identificação original. Baixar o PDF não comprova que a etiqueta foi impressa ou fixada. Se a gráfica usar outro gabarito, será necessário adaptar o arquivo.</p></section>'''
app.jinja_loader=ChoiceLoader([DictLoader(OP_TEMPLATES),app.jinja_loader])


app.jinja_env.globals['PUBLIC_URL_MOBILE']=PUBLIC_URL

# Instalação na tela inicial: recursos públicos sem dados pessoais ou cache do acervo.
@app.get('/manifest.json')
def app_manifest():
    return Response(json.dumps(dict(id='/',name='Patrimônio Carajás',short_name='Patrimônio',
        description='Gestão patrimonial de projetos · NGI ICMBio Carajás',lang='pt-BR',start_url='/',scope='/',
        display='standalone',background_color='#F4F5F1',theme_color='#0B3325',
        icons=[dict(src=url_for('app_icon',size=n),sizes=f'{n}x{n}',type='image/png',purpose='any maskable') for n in (192,512)]),ensure_ascii=False),mimetype='application/manifest+json')


@lru_cache(maxsize=3)
def icone_aplicativo(size):
    # Marca simples de folha, desenhada em código e com margem segura para máscaras.
    im = Image.new('RGB', (size, size), '#0B3325')
    draw = ImageDraw.Draw(im)

    def xy(x, y):
        return (int(size * x), int(size * y))

    draw.ellipse([xy(0.28, 0.22), xy(0.70, 0.68)], fill='#14513A')
    draw.polygon(
        [
            xy(0.34, 0.67),
            xy(0.35, 0.39),
            xy(0.48, 0.28),
            xy(0.69, 0.24),
            xy(0.64, 0.48),
            xy(0.51, 0.62),
        ],
        outline='#C7F26B',
        width=max(2, int(size * 0.018)),
    )
    draw.line([xy(0.30, 0.76), xy(0.57, 0.38)], fill='#C7F26B', width=max(2, int(size * 0.025)))
    draw.line([xy(0.42, 0.60), xy(0.59, 0.56)], fill='#C7F26B', width=max(2, int(size * 0.015)))
    out = io.BytesIO()
    im.save(out, format='PNG')
    return out.getvalue()


@app.get('/app-icon-<int:size>.png')
def app_icon(size):
    if size not in (180,192,512):abort(404)
    return Response(icone_aplicativo(size),mimetype='image/png')


@app.get('/sw.js')
def app_service_worker():
    # Não armazena HTML autenticado, fotos, tokens ou dados de outros usuários.
    script="self.addEventListener('install',()=>self.skipWaiting());self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));self.addEventListener('fetch',e=>{if(e.request.method==='GET'&&new URL(e.request.url).origin===self.location.origin)e.respondWith(fetch(e.request));});"
    return Response(script,mimetype='application/javascript',headers={'Service-Worker-Allowed':'/'})


def configurar_admin_environment():
    email = os.environ.get("ADMIN_EMAIL", "").strip().casefold()
    senha = os.environ.get("ADMIN_PASSWORD", "")
    nome = os.environ.get("ADMIN_NOME", "João Paulo Santos").strip()
    if not senha:
        return
    if (
        not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)
        or len(email) > 254
        or not 2 <= len(nome) <= 120
        or not 12 <= len(senha) <= 128
    ):
        raise RuntimeError(
            "Confira ADMIN_EMAIL, ADMIN_NOME e ADMIN_PASSWORD (12 a 128 caracteres)."
        )
    with app.app_context():
        try:
            # Serializa a configuração entre os processos do Gunicorn.
            if db.engine.dialect.name == "postgresql":
                db.session.execute(text("SELECT pg_advisory_xact_lock(739105631)"))
            usuario = db.session.scalar(select(Usuario).where(Usuario.email == email))
            alterado = False
            if usuario is None:
                usuario = Usuario(
                    email=email, nome=nome,
                    senha_hash=generate_password_hash(senha),
                )
                db.session.add(usuario)
                alterado = True
            elif not check_password_hash(usuario.senha_hash, senha) or not usuario.ativo:
                usuario.senha_hash = generate_password_hash(senha)
                usuario.ativo = True
                usuario.versao_sessao += 1
                alterado = True
            if alterado:
                # Libera tentativas anteriores desse e-mail após a redefinição.
                email_hash = digest(email)
                db.session.execute(
                    delete(TentativaLogin).where(TentativaLogin.email_hash == email_hash)
                )
            db.session.commit()
            app.logger.info("Administrador do Environment configurado.")
        except SQLAlchemyError as erro:
            db.session.rollback()
            app.logger.error("Configuração do administrador: %s", type(erro).__name__)
            raise RuntimeError(
                "Não foi possível configurar o administrador. Confira o banco do patrimônio."
            ) from None


def preparar_estrutura():
    with app.app_context():
        if db.engine.dialect.name == "postgresql":
            with db.engine.begin() as conn:
                conn.execute(text("SELECT pg_advisory_xact_lock(739105632)"))
                conn.execute(text("CREATE SCHEMA IF NOT EXISTS patrimonio"))
                db.metadata.create_all(conn)
                conn.execute(text("ALTER TABLE patrimonio.usuarios ADD COLUMN IF NOT EXISTS perfil VARCHAR(30) NOT NULL DEFAULT 'Administrador'"))
                conn.execute(text("ALTER TABLE patrimonio.convenios ADD COLUMN IF NOT EXISTS revisao INTEGER NOT NULL DEFAULT 1"))
                conn.execute(text("ALTER TABLE patrimonio.bens ADD COLUMN IF NOT EXISTS convenio_id INTEGER REFERENCES patrimonio.convenios(id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_bens_convenio_id ON patrimonio.bens (convenio_id)"))
                conn.execute(text("ALTER TABLE patrimonio.bens ADD COLUMN IF NOT EXISTS base_id INTEGER REFERENCES patrimonio.bases_locais(id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_bens_base_id ON patrimonio.bens (base_id)"))
                conn.execute(text("ALTER TABLE patrimonio.bens ADD COLUMN IF NOT EXISTS etiqueta_situacao VARCHAR(30) NOT NULL DEFAULT 'Não verificada'"))
                conn.execute(text("ALTER TABLE patrimonio.bens ADD COLUMN IF NOT EXISTS encerrado BOOLEAN NOT NULL DEFAULT FALSE"))
                conn.execute(text("ALTER TABLE patrimonio.bens ADD COLUMN IF NOT EXISTS encerrado_em TIMESTAMPTZ"))
                conn.execute(text("ALTER TABLE patrimonio.bens ADD COLUMN IF NOT EXISTS categoria_id INTEGER REFERENCES patrimonio.categorias(id)"))
                conn.execute(text("ALTER TABLE patrimonio.bens ADD COLUMN IF NOT EXISTS categoria VARCHAR(100) NOT NULL DEFAULT ''"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_bens_categoria_id ON patrimonio.bens(categoria_id)"))
                conn.execute(text("ALTER TABLE patrimonio.bens ADD COLUMN IF NOT EXISTS coordenacao_id INTEGER REFERENCES patrimonio.coordenacoes(id)"))
                conn.execute(text("ALTER TABLE patrimonio.bens ADD COLUMN IF NOT EXISTS coordenacao VARCHAR(20) NOT NULL DEFAULT ''"))
                conn.execute(text("ALTER TABLE patrimonio.bens ADD COLUMN IF NOT EXISTS classificacao VARCHAR(30) NOT NULL DEFAULT 'Patrimônio'"))
                conn.execute(text("ALTER TABLE patrimonio.bens ADD COLUMN IF NOT EXISTS classificacao_justificativa TEXT NOT NULL DEFAULT ''"))
                # Ajuste antigo (época da regra dos R$ 200,00): não reclassifica bens já decididos.
                conn.execute(text("UPDATE patrimonio.bens SET classificacao='Não é patrimônio' WHERE valor < 200 AND classificacao='Patrimônio' AND classificacao_justificativa=''"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_bens_coordenacao_id ON patrimonio.bens(coordenacao_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_bens_encerrado ON patrimonio.bens (encerrado)"))
                conn.execute(text("ALTER TABLE patrimonio.inventarios ADD COLUMN IF NOT EXISTS prazo DATE"))
                conn.execute(text("ALTER TABLE patrimonio.inventarios ADD COLUMN IF NOT EXISTS convenio_id INTEGER REFERENCES patrimonio.convenios(id)"))
                conn.execute(text("ALTER TABLE patrimonio.bens ADD COLUMN IF NOT EXISTS nota_fiscal VARCHAR(60) NOT NULL DEFAULT ''"))
                conn.execute(text("ALTER TABLE patrimonio.bens ADD COLUMN IF NOT EXISTS fornecedor VARCHAR(160) NOT NULL DEFAULT ''"))
                conn.execute(text("ALTER TABLE patrimonio.bens ADD COLUMN IF NOT EXISTS forma_ingresso VARCHAR(40) NOT NULL DEFAULT 'Compra'"))
                conn.execute(text("ALTER TABLE patrimonio.bens ADD COLUMN IF NOT EXISTS ingresso_detalhe VARCHAR(200) NOT NULL DEFAULT ''"))
                conn.execute(text("ALTER TABLE patrimonio.convenios ADD COLUMN IF NOT EXISTS valor NUMERIC(14, 2)"))
                conn.execute(text("ALTER TABLE patrimonio.convenios ADD COLUMN IF NOT EXISTS gestor VARCHAR(160) NOT NULL DEFAULT ''"))
                conn.execute(text("ALTER TABLE patrimonio.inventarios ADD COLUMN IF NOT EXISTS comissao VARCHAR(1000) NOT NULL DEFAULT ''"))
                conn.execute(text("REVOKE ALL ON SCHEMA patrimonio FROM PUBLIC, anon, authenticated"))
                conn.execute(text("REVOKE ALL ON ALL TABLES IN SCHEMA patrimonio FROM PUBLIC, anon, authenticated"))
                conn.execute(text("REVOKE ALL ON ALL SEQUENCES IN SCHEMA patrimonio FROM PUBLIC, anon, authenticated"))
                for tabela in db.metadata.sorted_tables:
                    conn.execute(text(f'ALTER TABLE patrimonio."{tabela.name}" ENABLE ROW LEVEL SECURITY'))
        else:
            db.create_all()
            with db.engine.begin() as conn:
                campos_inv={col['name'] for col in inspect(conn).get_columns('inventarios')}
                if 'prazo' not in campos_inv:conn.execute(text('ALTER TABLE inventarios ADD COLUMN prazo DATE'))
                if 'convenio_id' not in campos_inv:conn.execute(text('ALTER TABLE inventarios ADD COLUMN convenio_id INTEGER REFERENCES convenios(id)'))
                if 'comissao' not in campos_inv:conn.execute(text("ALTER TABLE inventarios ADD COLUMN comissao VARCHAR(1000) NOT NULL DEFAULT ''"))
                existentes={col['name'] for col in inspect(conn).get_columns('bens')}
                if 'etiqueta_situacao' not in existentes:conn.execute(text("ALTER TABLE bens ADD COLUMN etiqueta_situacao VARCHAR(30) NOT NULL DEFAULT 'Não verificada'"))
                if 'categoria_id' not in existentes:
                    conn.execute(text('ALTER TABLE bens ADD COLUMN categoria_id INTEGER REFERENCES categorias(id)'))
                if 'categoria' not in existentes:
                    conn.execute(text("ALTER TABLE bens ADD COLUMN categoria VARCHAR(100) NOT NULL DEFAULT ''"))
                if 'coordenacao_id' not in existentes:
                    conn.execute(text('ALTER TABLE bens ADD COLUMN coordenacao_id INTEGER REFERENCES coordenacoes(id)'))
                if 'coordenacao' not in existentes:
                    conn.execute(text("ALTER TABLE bens ADD COLUMN coordenacao VARCHAR(20) NOT NULL DEFAULT ''"))
                if 'classificacao' not in existentes:
                    conn.execute(text("ALTER TABLE bens ADD COLUMN classificacao VARCHAR(30) NOT NULL DEFAULT 'Patrimônio'"))
                if 'classificacao_justificativa' not in existentes:
                    conn.execute(text("ALTER TABLE bens ADD COLUMN classificacao_justificativa TEXT NOT NULL DEFAULT ''"))
                conn.execute(text("UPDATE bens SET classificacao='Não é patrimônio' WHERE valor < 200 AND classificacao='Patrimônio' AND classificacao_justificativa=''"))
                if 'encerrado' not in existentes:
                    conn.execute(text('ALTER TABLE bens ADD COLUMN encerrado BOOLEAN NOT NULL DEFAULT FALSE'))
                if 'encerrado_em' not in existentes:
                    conn.execute(text('ALTER TABLE bens ADD COLUMN encerrado_em DATETIME'))
                if 'nota_fiscal' not in existentes:
                    conn.execute(text("ALTER TABLE bens ADD COLUMN nota_fiscal VARCHAR(60) NOT NULL DEFAULT ''"))
                if 'fornecedor' not in existentes:
                    conn.execute(text("ALTER TABLE bens ADD COLUMN fornecedor VARCHAR(160) NOT NULL DEFAULT ''"))
                if 'forma_ingresso' not in existentes:
                    conn.execute(text("ALTER TABLE bens ADD COLUMN forma_ingresso VARCHAR(40) NOT NULL DEFAULT 'Compra'"))
                if 'ingresso_detalhe' not in existentes:
                    conn.execute(text("ALTER TABLE bens ADD COLUMN ingresso_detalhe VARCHAR(200) NOT NULL DEFAULT ''"))
                campos_conv = {col['name'] for col in inspect(conn).get_columns('convenios')}
                if 'valor' not in campos_conv:
                    conn.execute(text('ALTER TABLE convenios ADD COLUMN valor NUMERIC(14, 2)'))
                if 'gestor' not in campos_conv:
                    conn.execute(text("ALTER TABLE convenios ADD COLUMN gestor VARCHAR(160) NOT NULL DEFAULT ''"))
            with db.engine.begin() as conn:
                if "perfil" not in {col["name"] for col in inspect(conn).get_columns("usuarios")}:
                    conn.execute(text("ALTER TABLE usuarios ADD COLUMN perfil VARCHAR(30) NOT NULL DEFAULT 'Administrador'"))
                if "convenio_id" not in {col["name"] for col in inspect(conn).get_columns("bens")}:
                    conn.execute(text("ALTER TABLE bens ADD COLUMN convenio_id INTEGER REFERENCES convenios(id)"))
            if "base_id" not in {col["name"] for col in inspect(db.engine).get_columns("bens")}:
                with db.engine.begin() as conn:
                    conn.execute(text("ALTER TABLE bens ADD COLUMN base_id INTEGER REFERENCES bases_locais(id)"))


# ============================================================
# RECUPERAÇÃO DE SENHA — token aleatório, hash no banco e uso único
# ============================================================
class RecuperacaoSenha(db.Model):
    __tablename__ = 'recuperacoes_senha'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('patrimonio.usuarios.id'), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    versao_sessao = db.Column(db.Integer, nullable=False)
    criado_em = db.Column(db.BigInteger, nullable=False)
    expira_em = db.Column(db.BigInteger, nullable=False, index=True)
    usado_em = db.Column(db.BigInteger, nullable=True)


class TentativaRecuperacao(db.Model):
    __tablename__ = 'tentativas_recuperacao'
    id = db.Column(db.Integer, primary_key=True)
    ip_hash = db.Column(db.String(64), nullable=False, index=True)
    email_hash = db.Column(db.String(64), nullable=False, index=True)
    finalidade = db.Column(db.String(16), nullable=False)
    instante = db.Column(db.BigInteger, nullable=False, index=True)


MENSAGEM_RECUPERACAO = 'Se o e-mail estiver cadastrado e ativo, você receberá um link para redefinir sua senha. Confira também o spam. Se já solicitou, aguarde alguns minutos.'


def configuracao_email():
    # Segredos exclusivamente no Environment; não aparecem em HTML nem logs.
    host = os.environ.get('EMAIL_HOST', os.environ.get('SMTP_HOST', 'smtp.gmail.com')).strip()
    porta = os.environ.get('EMAIL_PORT', os.environ.get('SMTP_PORT', '587')).strip()
    remetente = os.environ.get('EMAIL_USER', os.environ.get('SMTP_USER', 'ngicarajasadm@gmail.com')).strip()
    senha = os.environ.get('EMAIL_PASSWORD', os.environ.get('SMTP_PASSWORD', '')).replace(' ', '').strip()
    origem = urlsplit(PUBLIC_URL)
    if (not host or porta not in {'465', '587'} or not senha or
        not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', remetente) or
        origem.scheme != 'https' or not origem.netloc or origem.username or origem.password or
        origem.query or origem.fragment or origem.path not in {'', '/'}):
        raise ValueError('Configure EMAIL_HOST, EMAIL_PORT (587 ou 465), EMAIL_USER, EMAIL_PASSWORD e PUBLIC_URL HTTPS no Environment.')
    return host, int(porta), remetente, senha


def enviar_email_sistema(destinatario, assunto, corpo, corpo_html=None):
    host, porta, remetente, senha = configuracao_email()
    mensagem = EmailMessage()
    mensagem['From'] = formataddr(('Patrimônio Carajás', remetente))
    mensagem['To'] = destinatario
    mensagem['Subject'] = assunto
    mensagem.set_content(corpo)
    if corpo_html:
        mensagem.add_alternative(corpo_html, subtype='html')
    contexto = ssl.create_default_context()
    # Nunca permite autenticação ou envio sem criptografia e certificado válido.
    cliente = smtplib.SMTP_SSL(host, porta, timeout=8, context=contexto) if porta == 465 else smtplib.SMTP(host, porta, timeout=8)
    with cliente as smtp:
        if porta == 587:
            smtp.ehlo()
            smtp.starttls(context=contexto)
            smtp.ehlo()
        smtp.login(remetente, senha)
        if smtp.send_message(mensagem, from_addr=remetente, to_addrs=[destinatario]):
            raise smtplib.SMTPException('Mensagem não aceita pelo servidor.')


def limitar_recuperacao(email, finalidade='solicitar'):
    agora = int(time.time())
    ip_hash = digest('recuperacao-ip:' + (request.remote_addr or 'desconhecido'))
    email_hash = digest('recuperacao-email:' + email)
    if db.engine.dialect.name == 'postgresql':
        # Ordem fixa das travas evita corrida entre workers e impasse entre IP/e-mail.
        for chave in sorted({int(ip_hash[:16],16)-(1<<63), int(email_hash[:16],16)-(1<<63)}):
            db.session.execute(text('SELECT pg_advisory_xact_lock(:chave)'), {'chave': chave})
    por_ip = db.session.scalar(select(func.count()).select_from(TentativaRecuperacao).where(
        TentativaRecuperacao.ip_hash==ip_hash, TentativaRecuperacao.finalidade==finalidade,
        TentativaRecuperacao.instante>=agora-900)) or 0
    por_email = db.session.scalar(select(func.count()).select_from(TentativaRecuperacao).where(
        TentativaRecuperacao.email_hash==email_hash, TentativaRecuperacao.finalidade==finalidade,
        TentativaRecuperacao.instante>=agora-3600)) or 0
    if por_ip >= (25 if finalidade=='solicitar' else 20) or (finalidade=='solicitar' and por_email>=5):
        db.session.rollback()
        return False
    db.session.execute(delete(TentativaRecuperacao).where(TentativaRecuperacao.instante<agora-86400))
    db.session.add(TentativaRecuperacao(ip_hash=ip_hash,email_hash=email_hash,finalidade=finalidade,instante=agora))
    db.session.commit()
    return True


def emitir_recuperacao(email, autor_id=None):
    agora = int(time.time())
    usuario = db.session.scalar(select(Usuario).where(Usuario.email==email,Usuario.ativo.is_(True))
        .with_for_update().execution_options(populate_existing=True))
    if not usuario:
        db.session.rollback()
        return False
    ultima = db.session.scalar(select(func.max(RecuperacaoSenha.criado_em)).where(
        RecuperacaoSenha.usuario_id==usuario.id,RecuperacaoSenha.usado_em.is_(None),RecuperacaoSenha.expira_em>agora))
    if ultima and ultima>agora-60:
        db.session.rollback()
        return False
    codigo = secrets.token_urlsafe(32)
    registro = RecuperacaoSenha(usuario_id=usuario.id,token_hash=digest('reset:'+codigo),
        versao_sessao=usuario.versao_sessao,criado_em=agora,expira_em=agora+1800)
    db.session.add(registro)
    db.session.execute(delete(RecuperacaoSenha).where(RecuperacaoSenha.expira_em<agora-86400))
    db.session.flush()
    registro_id = registro.id
    nome, destinatario = usuario.nome, usuario.email
    if autor_id:
        db.session.add(AuditoriaUsuario(autor_id=autor_id,usuario_id=usuario.id,acao='Solicitação administrativa de link para redefinir senha'))
    db.session.commit()
    link = PUBLIC_URL + url_for('redefinir_senha',codigo=codigo)
    corpo = (f'Olá, {nome}.\n\nRecebemos uma solicitação para redefinir sua senha no Patrimônio Carajás.\n'
        f'Acesse o link abaixo em até 30 minutos:\n{link}\n\n'
        'O link funciona uma única vez. Se você não solicitou, ignore esta mensagem: sua senha não foi alterada.\n\nNGI ICMBio Carajás')
    corpo_html = ('<!doctype html><html lang="pt-BR"><body style="font-family:Arial,sans-serif;background:#F4F5F1;padding:24px;color:#0E3B2B">'
        '<div style="max-width:560px;margin:auto;background:white;padding:32px;border-radius:16px;border-top:6px solid #0B3325">'
        '<h2>Patrimônio Carajás</h2><p>Olá, '+html_escape(nome)+'.</p><p>Você solicitou uma nova senha.</p>'
        '<p><a style="display:inline-block;background:#0E3B2B;color:white;padding:15px 22px;border-radius:8px;text-decoration:none" href="'+html_escape(link,quote=True)+'">Redefinir minha senha</a></p>'
        '<p>Este link expira em <strong>30 minutos</strong> e funciona uma única vez.</p>'
        '<p>Se não solicitou, ignore esta mensagem. Sua senha continua a mesma.</p><hr><small>NGI ICMBio Carajás</small></div></body></html>')
    try:
        enviar_email_sistema(destinatario,'Redefinir senha · Patrimônio Carajás',corpo,corpo_html)
    except (OSError, smtplib.SMTPException, ValueError):
        # Invalida o link se não houve confirmação de envio; nunca registra token/senha.
        db.session.execute(RecuperacaoSenha.__table__.update().where(RecuperacaoSenha.id==registro_id).values(usado_em=int(time.time())))
        db.session.commit()
        app.logger.warning('Envio de recuperação não confirmado. Confira SMTP no Render e execute testar-email.')
        return False
    return True


def tela_recuperacao(modo, erro=None, mensagem=None, valido=True):
    # Reutiliza a identidade visual do login sem alterar o restante do sistema.
    inicio = LOGIN_TEMPLATE.index('<h2>Bem-vindo de volta.</h2>')
    fim = LOGIN_TEMPLATE.index('<p class="info">', inicio)
    conteudo = r'''<h2>{{ 'Defina sua nova senha.' if modo=='redefinir' else 'Esqueceu sua senha?' }}</h2>
<p>{{ 'Escolha uma senha de 12 a 128 caracteres.' if modo=='redefinir' and valido else 'Informe o e-mail cadastrado para receber um link de recuperação.' if modo=='solicitar' else 'Solicite outro link para continuar.' }}</p>
{% if erro %}<div class="error" role="alert">{{ erro }}</div>{% endif %}
{% if mensagem %}<div role="status" style="padding:14px;background:#E1F0E6;color:#15573F;border-radius:8px;line-height:1.6;font-size:13px">{{ mensagem }}</div>{% endif %}
{% if valido and not mensagem %}<form method="post"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
{% if modo=='solicitar' %}<label for="rec-email">E-mail cadastrado</label><input id="rec-email" type="email" name="email" required maxlength="254" autocomplete="email">
{% else %}<label for="rec-senha">Nova senha</label><input id="rec-senha" type="password" name="senha" required minlength="12" maxlength="128" autocomplete="new-password"><label for="rec-confirmacao">Repita a nova senha</label><input id="rec-confirmacao" type="password" name="confirmacao" required minlength="12" maxlength="128" autocomplete="new-password">{% endif %}
<button type="submit">{{ 'Salvar nova senha' if modo=='redefinir' else 'Enviar link de recuperação' }}</button></form>{% endif %}
<p><a style="color:#15573F;text-decoration:underline" href="{{ url_for('login') }}">Voltar ao login</a>{% if modo=='redefinir' and not valido %} · <a style="color:#15573F;text-decoration:underline" href="{{ url_for('esqueci_senha') }}">Solicitar novo link</a>{% endif %}</p>'''
    return render_template_string(LOGIN_TEMPLATE[:inicio]+conteudo+LOGIN_TEMPLATE[fim:],modo=modo,erro=erro,mensagem=mensagem,valido=valido)


@app.route('/esqueci-senha',methods=['GET','POST'])
def esqueci_senha():
    if request.method=='POST':
        email=request.form.get('email','').strip().casefold()[:254]
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):
            return tela_recuperacao('solicitar',erro='Informe um e-mail válido.'),422
        # Falha de configuração é igual para qualquer endereço, sem revelar cadastro.
        try:
            configuracao_email()
        except ValueError:
            return tela_recuperacao('solicitar',erro='A recuperação por e-mail ainda não está disponível. Procure o administrador.'),503
        if limitar_recuperacao(email):
            emitir_recuperacao(email)
        return tela_recuperacao('solicitar',mensagem=MENSAGEM_RECUPERACAO)
    return tela_recuperacao('solicitar')


def buscar_recuperacao(codigo):
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}',codigo):
        return None
    return db.session.scalar(select(RecuperacaoSenha).where(RecuperacaoSenha.token_hash==digest('reset:'+codigo)))


@app.route('/redefinir-senha/<codigo>', methods=['GET', 'POST'])
def redefinir_senha(codigo):
    if request.method == 'POST' and not limitar_recuperacao('', finalidade='confirmar'):
        return (
            tela_recuperacao(
                'redefinir',
                erro='Muitas tentativas. Aguarde 15 minutos e solicite um novo link.',
                valido=False,
            ),
            429,
        )
    registro = buscar_recuperacao(codigo)
    usuario = None
    if registro:
        # Trava sempre o usuário antes do token, como na emissão e edição administrativa.
        usuario = (
            db.session.scalar(
                select(Usuario)
                .where(Usuario.id == registro.usuario_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if request.method == 'POST'
            else db.session.get(Usuario, registro.usuario_id)
        )
        if request.method == 'POST':
            registro = db.session.scalar(
                select(RecuperacaoSenha)
                .where(RecuperacaoSenha.id == registro.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
    if (
        not registro
        or registro.usado_em is not None
        or registro.expira_em <= int(time.time())
        or not usuario
        or not usuario.ativo
        or registro.versao_sessao != usuario.versao_sessao
    ):
        db.session.rollback()
        return (
            tela_recuperacao(
                'redefinir', erro='Este link é inválido, expirou ou já foi utilizado.', valido=False
            ),
            400,
        )
    if request.method == 'POST':
        senha = request.form.get('senha', '')
        confirmacao = request.form.get('confirmacao', '')
        if not 12 <= len(senha) <= 128 or senha != confirmacao:
            db.session.rollback()
            return (
                tela_recuperacao(
                    'redefinir',
                    erro='Informe uma senha de 12 a 128 caracteres e repita exatamente a mesma senha.',
                ),
                422,
            )
        usuario.senha_hash = generate_password_hash(senha)
        usuario.versao_sessao += 1
        registro.usado_em = int(time.time())
        db.session.add(
            AuditoriaUsuario(
                autor_id=usuario.id,
                usuario_id=usuario.id,
                acao='Senha redefinida por link enviado ao e-mail cadastrado',
            )
        )
        db.session.execute(
            delete(TentativaLogin).where(TentativaLogin.email_hash == digest(usuario.email))
        )
        db.session.commit()
        session.clear()
        flash('Senha atualizada. Entre com sua nova senha.')
        return redirect(url_for('login'))
    db.session.rollback()
    return tela_recuperacao('redefinir')


@app.post('/cadastros/usuarios/<int:usuario_id>/enviar-link-senha')
@login_obrigatorio
def enviar_link_usuario(usuario_id):
    if g.usuario.perfil!='Administrador':
        abort(403)
    usuario=db.session.get(Usuario,usuario_id)
    if not usuario:
        abort(404)
    if not usuario.ativo:
        flash('Ative o usuário antes de enviar o link de senha.')
    else:
        try:
            configuracao_email()
        except ValueError:
            flash('Configure o envio de e-mail no Environment e execute testar-email no Shell do Render.')
            return redirect(url_for('usuarios_cadastro'))
        if not limitar_recuperacao(usuario.email):
            flash('Limite de solicitações atingido. Aguarde antes de reenviar.')
        elif emitir_recuperacao(usuario.email,autor_id=g.usuario.id):
            flash('Link de senha enviado ao e-mail cadastrado. Validade: 30 minutos.')
        else:
            flash('Já existe um link solicitado há menos de um minuto, ou o envio não foi confirmado. Confira o e-mail e o log do Render.')
    return redirect(url_for('usuarios_cadastro'))


@app.cli.command('testar-email')
def testar_email():
    """Envia uma mensagem de teste somente ao próprio remetente configurado."""
    try:
        _,_,remetente,_=configuracao_email()
        enviar_email_sistema(remetente,'Teste de envio · Patrimônio Carajás',
            'A configuração de envio do Patrimônio Carajás está funcionando. Esta mensagem não contém senha ou link de acesso.')
    except smtplib.SMTPAuthenticationError:
        raise click.ClickException('Gmail recusou a autenticação. Confira EMAIL_USER e a senha de app em EMAIL_PASSWORD.') from None
    except (OSError,smtplib.SMTPException,ValueError):
        raise click.ClickException('Envio não confirmado. Confira EMAIL_HOST/PORT/USER/PASSWORD e PUBLIC_URL. No Render Free, as portas SMTP são bloqueadas; use uma instância paga para SMTP.') from None
    click.echo('Mensagem de teste aceita pelo Gmail. Confira a caixa de entrada e o spam do remetente.')


# ============================================================
# CONFERÊNCIA EM CAMPO — QR atual, resultado explícito e próximo bem
# ============================================================
def identificar_codigo_campo(codigo):
    """Aceita apenas QR deste sistema, caminho /bem/id ou identificação literal."""
    if not codigo:
        return None, None
    try:
        partes=urlsplit(codigo)
        if partes.scheme or partes.netloc:
            if partes.scheme not in ('https','http') or partes.netloc not in (urlsplit(PUBLIC_URL).netloc,request.host):
                return None, 'Este QR Code não pertence a este sistema. Leia a plaqueta do patrimônio.'
            caminho=partes.path
        elif codigo.startswith('/'):
            caminho=partes.path
        else:
            return None, None
        match=re.fullmatch(r'/bem/(\d+)/?',caminho)
        if not match:
            return None, 'O QR Code não contém uma ficha de bem válida.'
        return int(match.group(1)), None
    except ValueError:
        return None, 'QR Code inválido. Leia novamente ou digite a identificação.'


@app.get('/inventario/campo')
@login_obrigatorio
def inventario_campo():
    codigo = request.args.get('codigo', '').strip()[:500]
    bem_id, erro_codigo = identificar_codigo_campo(codigo)
    if g.usuario.leitura:
        if codigo and not erro_codigo:
            consulta = (
                select(Bem).where(Bem.id == bem_id)
                if bem_id
                else select(Bem)
                .where(
                    or_(
                        func.lower(Bem.numero_ngi) == codigo.casefold(),
                        Bem.numero_ngi == (formatar_patrimonio(codigo) if codigo.isdigit() and len(codigo) < 10 else codigo),
                        func.lower(Bem.plaqueta_original) == codigo.casefold(),
                        func.lower(Bem.serie) == codigo.casefold(),
                    )
                )
                .limit(2)
            )
            encontrados = db.session.scalars(consulta).all()
            if len(encontrados) == 1:
                return redirect(url_for('ficha', bem_id=encontrados[0].id, consulta=1))
            flash(
                'Mais de um bem corresponde à identificação. Use a lista para selecionar.'
                if encontrados
                else 'Bem não encontrado. Consulte a lista de bens.'
            )
        elif erro_codigo:
            flash(erro_codigo)
        return redirect(
            url_for('listar_bens', q=codigo[:120] if not erro_codigo and not bem_id else '')
        )
    inv_id = inteiro(request.args.get('inventario_id'))
    if inv_id:
        inv = carregar(CampanhaInventario, inv_id)
    else:
        inv = db.session.scalar(
            select(CampanhaInventario)
            .where(CampanhaInventario.status == 'Aberto')
            .order_by(CampanhaInventario.id.desc())
            .limit(1)
        )
    contexto = session.get('inventario_campo', {})
    anterior = (
        contexto
        if contexto.get('usuario_id') == g.usuario.id
        and inv
        and contexto.get('inventario_id') == inv.id
        else {}
    )
    local = request.args.get('local', anterior.get('local', '')).strip()[:160]
    locais = []
    resumo = {}
    erro = erro_codigo
    if inv:
        campo = func.coalesce(
            func.nullif(ItemInventario.retrato['local'].as_string(), ''), 'Local não informado'
        )
        locais = db.session.scalars(
            select(campo).where(ItemInventario.inventario_id == inv.id).distinct().order_by(campo)
        ).all()
        if local and local not in locais:
            erro = 'O local selecionado não pertence a este inventário. Selecione um dos locais abaixo.'
            local = ''
        if not local and len(locais) == 1:
            local = locais[0]
        if inv.status == 'Aberto':
            session['inventario_campo'] = dict(
                usuario_id=g.usuario.id, inventario_id=inv.id, local=local
            )
        resumo = dict(
            db.session.execute(
                select(ItemInventario.status, func.count())
                .where(ItemInventario.inventario_id == inv.id)
                .group_by(ItemInventario.status)
            ).all()
        )
    if not inv:
        erro = 'Nenhum inventário está aberto. Abra um inventário antes de registrar a conferência em campo.'
    elif inv.status != 'Aberto':
        erro = 'Este inventário foi encerrado. Os resultados estão preservados; abra ou selecione um inventário em andamento.'
    elif g.usuario.leitura:
        erro = 'Seu perfil permite consultar os bens. O registro da conferência exige perfil Operador ou Administrador.'
    elif codigo and not erro:
        consulta = select(ItemInventario).join(Bem).where(ItemInventario.inventario_id == inv.id)
        if bem_id:
            consulta = consulta.where(ItemInventario.bem_id == bem_id)
        else:
            consulta = consulta.where(
                or_(
                    func.lower(Bem.numero_ngi) == codigo.casefold(),
                    Bem.numero_ngi == (formatar_patrimonio(codigo) if codigo.isdigit() and len(codigo) < 10 else codigo),
                    func.lower(Bem.plaqueta_original) == codigo.casefold(),
                    func.lower(Bem.serie) == codigo.casefold(),
                )
            )
        if local:
            consulta = consulta.where(campo == local)
        itens = db.session.scalars(consulta.limit(2)).all()
        if len(itens) == 1:
            return redirect(
                url_for('conferir_inventario', item_id=itens[0].id, campo='sim', local=local)
            )
        erro = (
            'Mais de um bem usa essa identificação. Confira a base e use o QR Code da ficha do bem.'
            if len(itens) > 1
            else 'Bem não encontrado no inventário e local selecionados. Confira a base ou pesquise na lista. A leitura não criou nem alterou registros.'
        )
    return tela_operacao(
        'inventario',
        'inv_campo',
        'Conferência em campo',
        inv=inv,
        campo_local_filtro=local,
        campo_locais=locais,
        campo_erro=erro,
        campo_codigo=codigo,
        campo_resumo=resumo,
        campo_bem_id=bem_id,
        campo_camera=request.args.get('camera') == '1'
        and not erro
        and bool(inv)
        and not g.usuario.leitura,
    )


OP_TEMPLATES['inv_campo']=r'''
<div class="field27-wrap"><div class="field27-title"><span class="eyebrow">INVENTÁRIO PELO CELULAR</span><h1>Conferência em campo</h1><p>Leia a plaqueta, confira o bem e registre o resultado.</p></div>
{% if campo_erro %}<div class="field27-message" role="alert">{{ campo_erro }}</div>{% endif %}
{% if inv %}<section class="panel field27-context"><strong>{{ inv.nome }}</strong><small>{{ inv.status }} · {{ inv.local }}</small><p>{{ (campo_resumo.values()|sum)-campo_resumo.get('Pendente',0) }} de {{ campo_resumo.values()|sum }} verificados no inventário · {{ campo_resumo.get('Pendente',0) }} pendentes</p></section>{% endif %}
{% if inv and inv.status=='Aberto' and not usuario.leitura %}<section class="panel field27-start"><form method="get" action="{{ url_for('inventario_campo') }}"><input type="hidden" name="inventario_id" value="{{ inv.id }}"><div class="field"><label for="campo-local">Local em que você está conferindo</label><select id="campo-local" name="local"><option value="">Todos os locais do inventário</option>{% for l in campo_locais %}<option value="{{ l }}" {{ 'selected' if campo_local_filtro==l }}>{{ l }}</option>{% endfor %}</select></div><div class="field"><label for="campo-codigo">Plaqueta ou número de série</label><input id="campo-codigo" name="codigo" maxlength="500" value="" placeholder="Digite se não conseguir ler o QR Code"></div><button class="btn" type="submit">Localizar pelo número</button></form><button class="btn primary field27-camera" type="button" data-home-camera="inventory">{{ icon('scan') }} Ler próximo bem</button><p class="hint">A leitura abre a conferência. O resultado só é registrado depois de você confirmar e salvar.</p><a class="text-action" href="{{ url_for('inventario_detalhe',inventario_id=inv.id,local=campo_local_filtro) }}">Buscar por nome / ver bens pendentes →</a></section>{% if campo_camera %}<script>document.addEventListener('DOMContentLoaded',()=>document.querySelector('.field27-camera')?.click());</script>{% endif %}
{% elif not inv and not usuario.leitura %}<a class="btn primary" href="{{ url_for('inventario',aba='cadastro') }}">Iniciar inventário</a>{% else %}<a class="btn" href="{{ url_for('inventario') }}">Consultar inventários</a>{% endif %}
{% if campo_bem_id %}<p><a class="text-action" href="{{ url_for('ficha',bem_id=campo_bem_id,consulta=1) }}">Consultar ficha completa do bem</a></p>{% endif %}
</div>'''

OP_TEMPLATES['inv_item_campo']=r'''
<div class="field27-wrap"><a class="back" href="{{ url_for('inventario_campo',inventario_id=inv.id,local=campo_local_filtro) }}">← Conferência em campo</a><div class="field27-title"><span class="eyebrow">{{ inv.nome }} · {{ campo_local_filtro or inv.local }}</span><h1>O bem está correto?</h1><p>Compare o que você encontrou com os dados abaixo.</p></div>{% include 'op_erros' %}
<section class="panel field27-asset"><div class="field27-photo">{% if ativo.tem_foto %}<img src="{{ url_for('foto_bem',bem_id=ativo.id) }}" alt="Foto de {{ ativo.nome }}">{% else %}{{ icon('box') }}<span>Sem foto cadastrada</span>{% endif %}</div><div><span class="field27-plaque">{{ ativo.numero_ngi or ativo.plaqueta_original or 'Sem plaqueta' }}</span><h2>{{ ativo.nome }}</h2><p>{{ ativo.marca }} · {{ ativo.modelo }}</p></div><dl><div><dt>Número de série</dt><dd>{{ ativo.serie or 'Não informado' }}</dd></div><div><dt>Local cadastrado</dt><dd>{{ ativo.local }}</dd></div><div><dt>Ambiente</dt><dd>{{ ativo.complemento or 'Não informado' }}</dd></div><div><dt>Responsável</dt><dd>{{ ativo.responsavel }}</dd></div><div><dt>Conservação</dt><dd>{{ ativo.conservacao }}</dd></div><div><dt>Situação</dt><dd>{{ ativo.situacao }}</dd></div></dl><a class="text-action" href="{{ url_for('ficha',bem_id=ativo.id,consulta=1) }}">Consultar ficha completa →</a></section>
{% if item.status!='Pendente' %}<div class="field27-message"><strong>Este bem já foi verificado: {{ item.status }}.</strong><p>{{ item.conferente_nome }} · {{ item.conferido_em|datahora }}. Salvar novamente registra uma revisão no histórico.</p></div>{% endif %}
{% if ativo.encerrado or ativo.revisao|string != item.retrato.get('revisao') %}<div class="field27-message"><strong>O cadastro mudou desde a abertura do inventário.</strong><p>Registre a divergência e descreva a situação encontrada. Na abertura: {{ item.retrato.local }} · {{ item.retrato.responsavel }} · {{ item.retrato.conservacao }}.</p></div>{% endif %}
<form method="post" class="panel field27-form" enctype="application/x-www-form-urlencoded"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><input type="hidden" name="revisao" value="{{ item.revisao }}"><input type="hidden" name="revisao_bem" value="{{ ativo.revisao }}"><h2>Resultado da verificação</h2><div class="field27-choices">{% for st,label,help in [('Conferido','Tudo correto','Encontrei o bem e os dados conferem.'),('Divergência','Há divergência','Encontrei algum problema ou informação diferente.')] %}<label class="field27-choice"><input type="radio" name="status" value="{{ st }}" required {{ 'checked' if valores.get('status',item.status)==st }}><span><strong>{{ label }}</strong><small>{{ help }}</small></span></label>{% endfor %}</div><div class="field field27-observation" id="field27-observation"><label for="inv-obs">Descreva o que encontrou <span id="field27-required">(obrigatório para divergência)</span></label><textarea id="inv-obs" name="observacao" maxlength="3000" rows="4" placeholder="Ex.: o bem está na sala de reuniões, mas consta na recepção; ou a cadeira está com o apoio quebrado.">{{ valores.get('observacao',item.observacao) }}</textarea><small>Informe a divergência com pelo menos 10 caracteres. O relato fica no inventário e não altera automaticamente o cadastro.</small></div><button class="btn primary field27-save" name="continuar" value="sim">Salvar conferência e ler próximo</button><button class="btn field27-save" name="continuar" value="nao">Salvar e voltar à lista</button><p class="hint">Registro por {{ usuario.nome }}, com data e hora ao salvar. Se não localizou outro bem, registre isso pela lista de pendentes.</p></form></div>
<script>(()=>{const form=document.querySelector('.field27-form'),radios=[...form.querySelectorAll('[name=status]')],obs=document.getElementById('inv-obs');function update(){const divergent=radios.find(r=>r.checked)?.value==='Divergência';obs.required=divergent;obs.minLength=divergent?10:0;document.getElementById('field27-required').textContent=divergent?'* obrigatório':'(opcional)';}radios.forEach(r=>r.addEventListener('change',update));update();})();</script>'''
# O scanner global tem fallback para navegadores sem BarcodeDetector (inclui iPhone).
OP_TEMPLATES['inv_scanner']=''


# Artes institucionais originais enviadas pelo usuário, incorporadas ao arquivo único.
# ============================================================
# OPERAÇÃO SEGURA: backup cifrado, restauração em banco vazio e monitoramento
# ============================================================
import gzip
import tempfile
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from sqlalchemy import LargeBinary, Numeric, DateTime, Date

class ExecucaoBackup(db.Model):
    __tablename__ = 'execucoes_backup'
    id = db.Column(db.String(32), primary_key=True)
    iniciado_em = db.Column(db.DateTime(timezone=True), nullable=False)
    concluido_em = db.Column(db.DateTime(timezone=True))
    status = db.Column(db.String(20), nullable=False)
    registros = db.Column(db.Integer, nullable=False, default=0)
    tamanho = db.Column(db.BigInteger, nullable=False, default=0)
    sha256 = db.Column(db.String(64), nullable=False, default='')
    objeto = db.Column(db.String(300), nullable=False, default='')

# Allowlist aplicada no servidor e usada também para montar a navegação.
# ---------- Integração com o SIGAD Carajás ----------
# O SIGAD envia, com uma chave secreta, os itens de compra classificados como patrimônio
# quando o material é recebido. Cada unidade vira uma entrada "Aguardando tombamento";
# o operador confere o bem em mãos e conclui o cadastro (série, plaqueta, local e foto).
LIMITE_ITENS_SIGAD = 200
LIMITE_UNIDADES_SIGAD = 500


def chave_integracao_sigad():
    chave = os.environ.get('INTEGRACAO_SIGAD_CHAVE', '').strip()
    return chave if len(chave) >= 32 else ''


def _txt_sigad(valor, limite):
    return ' '.join(str(valor if valor is not None else '').split())[:limite]


def _norm_sigad(texto):
    texto = unicodedata.normalize('NFKD', str(texto or '')).encode('ascii', 'ignore').decode().casefold()
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', texto).split())


def achar_convenio_sigad(texto):
    """'GLOBAL' no SIGAD encontra 'Global III' no Patrimônio, desde que só exista um parecido."""
    alvo = _norm_sigad(texto)
    if not alvo:
        return None
    convenios = db.session.scalars(select(Convenio).where(Convenio.ativo.is_(True))).all()
    exatos = [c for c in convenios if _norm_sigad(c.nome) == alvo]
    if len(exatos) == 1:
        return exatos[0]
    parecidos = [c for c in convenios if _norm_sigad(c.nome).startswith(alvo + ' ') or alvo.startswith(_norm_sigad(c.nome) + ' ')]
    return parecidos[0] if len(parecidos) == 1 else None


def achar_coordenacao_sigad(texto):
    alvo = _norm_sigad(texto)
    if not alvo:
        return None
    for c in db.session.scalars(select(Coordenacao).where(Coordenacao.ativo.is_(True))):
        if alvo in (_norm_sigad(c.sigla), _norm_sigad(c.nome)):
            return c
    return None


def _data_sigad(valor):
    try:
        return date.fromisoformat(str(valor)[:10]) if valor else None
    except ValueError:
        return None


def resposta_sigad(status, **dados):
    return jsonify(**dados), status


@csrf.exempt
@app.post('/api/integracao/sigad/entradas')
def sigad_receber():
    chave = chave_integracao_sigad()
    if not chave:
        return resposta_sigad(503, ok=False, mensagem='A integração com o SIGAD não está configurada no Patrimônio (INTEGRACAO_SIGAD_CHAVE).')
    autorizacao = request.headers.get('Authorization', '')
    if not autorizacao.startswith('Bearer ') or not hmac.compare_digest(autorizacao[7:].strip().encode(), chave.encode()):
        return resposta_sigad(401, ok=False, mensagem='Chave de integração inválida.')
    corpo = request.get_json(silent=True) if request.is_json else None
    if not isinstance(corpo, dict):
        return resposta_sigad(400, ok=False, mensagem='Envie os dados em JSON.')
    sid = inteiro(corpo.get('solicitacao_id'))
    protocolo = _txt_sigad(corpo.get('protocolo'), 40)
    itens = corpo.get('itens')
    if not sid or sid < 1 or not protocolo or not isinstance(itens, list) or not itens or len(itens) > LIMITE_ITENS_SIGAD:
        return resposta_sigad(422, ok=False, mensagem='Informe a solicitação, o protocolo e de 1 a 200 itens.')
    lidos = []
    for posicao, item in enumerate(itens, start=1):
        if not isinstance(item, dict):
            return resposta_sigad(422, ok=False, mensagem=f'Item {posicao} inválido.')
        item_id = inteiro(item.get('item_id'))
        nome = _txt_sigad(item.get('nome'), 300)
        quantidade = inteiro(item.get('quantidade'))
        if not item_id or item_id < 1 or len(nome) < 2 or not quantidade or not 1 <= quantidade <= LIMITE_UNIDADES_SIGAD:
            return resposta_sigad(422, ok=False, mensagem=f'Item {posicao}: confira o código, o nome e a quantidade (número inteiro de 1 a {LIMITE_UNIDADES_SIGAD}).')
        valor = None
        if item.get('valor_unitario') not in (None, ''):
            try:
                valor = Decimal(str(item.get('valor_unitario'))).quantize(Decimal('0.01'))
                if not valor.is_finite() or valor < 0 or valor > Decimal('999999999999.99'):
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                return resposta_sigad(422, ok=False, mensagem=f'Item {posicao}: valor unitário inválido.')
        lidos.append(dict(item_id=item_id, nome=nome, quantidade=quantidade, valor=valor,
                          fornecedor=_txt_sigad(item.get('fornecedor'), 300),
                          justificativa=str(item.get('justificativa') or '').strip()[:3000],
                          classificacao_justificativa=str(item.get('classificacao_justificativa') or '').strip()[:2000]))
    if sum(i['quantidade'] for i in lidos) > LIMITE_UNIDADES_SIGAD:
        return resposta_sigad(422, ok=False, mensagem=f'Envio com mais de {LIMITE_UNIDADES_SIGAD} unidades. Divida em partes.')
    convenio_txt = _txt_sigad(corpo.get('convenio'), 200)
    coordenacao_txt = _txt_sigad(corpo.get('coordenacao'), 100)
    convenio = achar_convenio_sigad(convenio_txt)
    coordenacao = achar_coordenacao_sigad(coordenacao_txt)
    aviso_nota = ''
    nota = corpo.get('nota_fiscal')
    if isinstance(nota, dict) and nota.get('conteudo_base64'):
        try:
            bruto = base64.b64decode(str(nota.get('conteudo_base64')), validate=True)
            arquivo = FileStorage(io.BytesIO(bruto), filename=_txt_sigad(nota.get('nome'), 140) or 'nota-fiscal.pdf',
                                  content_type=_txt_sigad(nota.get('tipo'), 80) or None)
            dados_nf, mime, ext = ler_arquivo_documento(arquivo)
            base_nome = re.sub(r'[^\w .()-]', '_', arquivo.filename)[:140].rsplit('.', 1)[0] or 'Nota fiscal'
            registro = db.session.get(EntradaSigadNota, sid) or EntradaSigadNota(sigad_solicitacao_id=sid)
            registro.nome, registro.mime, registro.dados = f'{base_nome}.{ext}', mime, dados_nf
            registro.sha256 = hashlib.sha256(dados_nf).hexdigest()
            db.session.add(registro)
        except ValueError as erro:
            aviso_nota = f'Nota fiscal não aproveitada: {erro}'
    comuns = dict(sigad_solicitacao_id=sid, protocolo=protocolo, convenio_texto=convenio_txt, convenio_id=convenio.id if convenio else None,
                  coordenacao_texto=coordenacao_txt, coordenacao_id=coordenacao.id if coordenacao else None,
                  solicitante=_txt_sigad(corpo.get('solicitante'), 200), contato=_txt_sigad(corpo.get('contato'), 200),
                  data_compra=_data_sigad(corpo.get('data_compra')), recebido_em=_data_sigad(corpo.get('recebido_em')),
                  recebido_por=_txt_sigad(corpo.get('recebido_por'), 200))
    existentes = set(db.session.scalars(select(EntradaSigad.chave).where(EntradaSigad.sigad_solicitacao_id == sid)))
    criadas = ja_existiam = 0
    for item in lidos:
        for unidade in range(1, item['quantidade'] + 1):
            chave_item = f"{sid}:{item['item_id']}:{unidade}"
            if chave_item in existentes:
                ja_existiam += 1
                continue
            db.session.add(EntradaSigad(chave=chave_item, sigad_item_id=item['item_id'], unidade=unidade, quantidade_total=item['quantidade'],
                                        nome=item['nome'], justificativa=item['justificativa'], valor_unitario=item['valor'],
                                        fornecedor=item['fornecedor'], classificacao_justificativa=item['classificacao_justificativa'], **comuns))
            criadas += 1
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return resposta_sigad(409, ok=False, mensagem='Este envio já estava sendo gravado. Tente novamente em alguns segundos.')
    aguardando = db.session.scalar(select(func.count(EntradaSigad.id)).where(
        EntradaSigad.sigad_solicitacao_id == sid, EntradaSigad.status == 'Aguardando tombamento')) or 0
    return resposta_sigad(200, ok=True, criadas=criadas, ja_existiam=ja_existiam, aguardando=aguardando,
                          convenio_encontrado=bool(convenio), coordenacao_encontrada=bool(coordenacao), aviso_nota=aviso_nota,
                          mensagem=f'{criadas} bem(ns) recebido(s) no Patrimônio' + (f'; {ja_existiam} já tinham chegado antes' if ja_existiam else '') + '.')


def valores_entrada_sigad(entrada):
    descricao = entrada.nome + (f"\nJustificativa da compra: {entrada.justificativa}" if entrada.justificativa else '')
    observacoes = f"Compra pelo SIGAD · protocolo {entrada.protocolo}" + (f" · recebido por {entrada.recebido_por}" if entrada.recebido_por else '') + \
        (f" em {entrada.recebido_em.strftime('%d/%m/%Y')}" if entrada.recebido_em else '') + '.'
    # O SIGAD só envia itens classificados como patrimônio; abaixo de R$ 250 a justificativa vem junto.
    fora_da_regra = classificacao_sugerida(entrada.valor_unitario) != 'Patrimônio'
    texto = f"Protocolo {entrada.protocolo} · unidade {entrada.unidade} de {entrada.quantidade_total} · solicitado por {entrada.solicitante or 'não informado'}"
    return dict(nome=entrada.nome[:160], descricao=descricao[:5000], valor=valor_brl_campo(entrada.valor_unitario),
                fornecedor=entrada.fornecedor[:160], convenio_id=entrada.convenio_id or '', coordenacao_id=entrada.coordenacao_id or '',
                data_aquisicao=(entrada.data_compra or entrada.recebido_em).isoformat() if (entrada.data_compra or entrada.recebido_em) else '',
                aquisicao_justificativa='' if entrada.valor_unitario is not None and (entrada.data_compra or entrada.recebido_em) else 'Compra registrada no SIGAD; conferir com a nota fiscal.',
                classificacao='Patrimônio',
                classificacao_justificativa=entrada.classificacao_justificativa if fora_da_regra else '',
                responsavel=entrada.solicitante[:160], responsavel_contato=entrada.contato[:160], situacao='Em uso', conservacao='Novo',
                observacoes=observacoes[:5000], possui_plaqueta='nao', serie_excecao='Informado',
                entrada_sigad_id=entrada.id, entrada_sigad_texto=texto)


class _ArquivoCopiado:
    def __init__(self, nome):
        self.filename = nome


def copiar_nota_entrada_sigad(bem, entrada):
    nota = db.session.get(EntradaSigadNota, entrada.sigad_solicitacao_id)
    if nota is not None:
        salvar_nota_fiscal(bem, _ArquivoCopiado(nota.nome), (nota.dados, nota.mime, nota.nome.rsplit('.', 1)[-1]))


@app.get('/bens/entradas-sigad')
@login_obrigatorio
def entradas_sigad():
    if g.usuario.leitura:
        abort(403)
    aba = request.args.get('aba', 'aguardando')
    status = {'aguardando': 'Aguardando tombamento', 'tombados': 'Tombado', 'descartados': 'Descartado'}
    if aba not in status:
        aba = 'aguardando'
    contagens = dict(db.session.execute(select(EntradaSigad.status, func.count(EntradaSigad.id)).group_by(EntradaSigad.status)).all())
    entradas = db.session.scalars(select(EntradaSigad).where(EntradaSigad.status == status[aba])
                                  .order_by(EntradaSigad.id.desc() if aba != 'aguardando' else EntradaSigad.id).limit(300)).all()
    bens = {b.id: b for b in db.session.scalars(select(Bem).where(Bem.id.in_([e.bem_id for e in entradas if e.bem_id] or [-1])))}
    convenios = {c.id: c.nome for c in db.session.scalars(select(Convenio))}
    coordenacoes = {c.id: c.sigla for c in db.session.scalars(select(Coordenacao))}
    return tela_operacao('bens', 'entradas_sigad', 'Entradas do SIGAD', aba=aba, entradas=entradas, bens_entradas=bens,
                         convenios_nomes=convenios, coordenacoes_siglas=coordenacoes, contagens=contagens,
                         integracao_ligada=bool(chave_integracao_sigad()), operacao_token=token_operacao())


@app.post('/bens/entradas-sigad/<int:entrada_id>/descartar')
@login_obrigatorio
def descartar_entrada_sigad(entrada_id):
    if g.usuario.leitura:
        abort(403)
    entrada = carregar(EntradaSigad, entrada_id, True)
    motivo = ' '.join(request.form.get('motivo', '').split())[:2000]
    if entrada.status != 'Aguardando tombamento':
        db.session.rollback()
        flash('Esta entrada já foi tratada.')
    elif len(motivo) < 10:
        db.session.rollback()
        flash('Explique o motivo do descarte com pelo menos 10 caracteres.')
    else:
        entrada.status = 'Descartado'
        entrada.motivo_descarte = motivo
        entrada.tratado_por = g.usuario.id
        entrada.tratado_em = datetime.now(timezone.utc)
        db.session.commit()
        flash('Entrada descartada. Ela não vira bem patrimonial.')
    return redirect(url_for('entradas_sigad'))


OP_TEMPLATES['entradas_sigad'] = r"""<div class="list-heading"><div><h1>Entradas do SIGAD</h1><p>Compras recebidas no SIGAD com itens classificados como patrimônio. Confira cada bem em mãos e conclua o tombamento.</p></div></div>
<nav class="registry-navigation" aria-label="Navegação dos bens"><a href="{{ url_for('listar_bens') }}">Bens cadastrados</a><a href="{{ url_for('cadastrar_bem') }}">Cadastrar bem</a><a href="{{ url_for('entradas_sigad') }}" class="current" aria-current="page">Entradas do SIGAD{% if entradas_sigad_pendentes %} ({{ entradas_sigad_pendentes }}){% endif %}</a></nav>
{% if not integracao_ligada %}<div class="callout"><strong>Integração ainda não ligada</strong><p>Para o SIGAD enviar as compras, crie a variável <code>INTEGRACAO_SIGAD_CHAVE</code> no Render, com a mesma chave configurada no SIGAD.</p></div>{% endif %}
<section class="panel"><nav class="registry-navigation" aria-label="Situação das entradas">{% for chave,rotulo,st in [('aguardando','Aguardando tombamento','Aguardando tombamento'),('tombados','Tombados','Tombado'),('descartados','Descartados','Descartado')] %}<a href="{{ url_for('entradas_sigad',aba=chave) }}" class="{{ 'current' if aba==chave }}">{{ rotulo }} ({{ contagens.get(st,0) }})</a>{% endfor %}</nav>
<div class="tablewrap"><table><thead><tr><th>Bem comprado</th><th>Compra no SIGAD</th><th>Valor unitário</th><th>Convênio</th><th>Coordenação</th><th>{{ 'Ação' if aba=='aguardando' else ('Bem cadastrado' if aba=='tombados' else 'Motivo') }}</th></tr></thead><tbody>
{% for e in entradas %}<tr><td><strong>{{ e.nome }}</strong><small class="table-sub">Unidade {{ e.unidade }} de {{ e.quantidade_total }}{% if e.fornecedor %} · {{ e.fornecedor }}{% endif %}</small></td>
<td>{{ e.protocolo }}<small class="table-sub">{{ e.solicitante or 'Solicitante não informado' }}{% if e.recebido_em %} · recebido em {{ e.recebido_em.strftime('%d/%m/%Y') }}{% endif %}</small></td>
<td>{{ e.valor_unitario|brl }}</td>
<td>{% if e.convenio_id %}{{ convenios_nomes.get(e.convenio_id) }}{% else %}<span class="sigad-aviso">{{ e.convenio_texto or 'Não informado' }} · escolher no tombamento</span>{% endif %}</td>
<td>{% if e.coordenacao_id %}{{ coordenacoes_siglas.get(e.coordenacao_id) }}{% else %}{{ e.coordenacao_texto or '—' }}{% endif %}</td>
<td>{% if aba=='aguardando' %}<a class="btn primary" href="{{ url_for('cadastrar_bem', entrada=e.id) }}">Tombar</a>
<details class="sigad-descartar"><summary>Descartar</summary><form method="post" action="{{ url_for('descartar_entrada_sigad', entrada_id=e.id) }}"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><label for="mot-{{ e.id }}">Motivo</label><textarea id="mot-{{ e.id }}" name="motivo" minlength="10" maxlength="2000" required placeholder="Ex.: item devolvido ao fornecedor"></textarea><button class="btn">Confirmar descarte</button></form></details>
{% elif aba=='tombados' %}{% set b = bens_entradas.get(e.bem_id) %}{% if b %}<a href="{{ url_for('ficha', bem_id=b.id) }}">{{ b.numero_ngi or b.plaqueta_original or 'Ficha do bem' }} →</a>{% endif %}<small class="table-sub">{{ e.tratado_em|datahora }}</small>
{% else %}{{ e.motivo_descarte }}<small class="table-sub">{{ e.tratado_em|datahora }}</small>{% endif %}</td></tr>
{% else %}<tr><td colspan="6" class="list-empty">{{ 'Nenhuma compra aguardando tombamento.' if aba=='aguardando' else 'Nada por aqui ainda.' }}</td></tr>{% endfor %}
</tbody></table></div><p class="hint">Cada unidade comprada aparece numa linha: 2 notebooks viram 2 entradas, cada uma com sua plaqueta. A nota fiscal enviada pelo SIGAD é anexada automaticamente ao bem tombado.</p></section>"""


# ---------- Central de ajuda ----------
# Passo a passo de cada módulo, em linguagem simples. Os conceitos (o que é
# tombamento, termo, inventário etc.) ficam no Guia patrimonial.
AJUDA_TOPICOS = [
    dict(id='primeiros-passos', modulo='Começo', titulo='Primeiros passos e perfis', resumo='Como entrar, o que cada perfil pode fazer e por onde começar.',
         quem='Todos os perfis', endpoint='inicio', rotulo='Ir para a página inicial',
         passos=['Entre com seu e-mail e senha. Se esqueceu a senha, use "Esqueci minha senha" na tela de entrada: o link chega no seu e-mail.',
                 'No menu da esquerda ficam os módulos. Você só vê o que o seu perfil pode usar.',
                 '<b>Administrador</b>: faz tudo, inclusive usuários, relatórios, decisão de baixa e encerramento do inventário.',
                 '<b>Operador</b>: cadastra bens, movimenta, emite termos, confere inventário, imprime plaquetas e faz o tombamento das compras do SIGAD.',
                 '<b>Gestor de convênio</b>: só consulta os bens, o encerramento e o relatório final dos convênios dele.',
                 '<b>Consulta</b>: só consulta a lista e a ficha dos bens. Não altera nada.',
                 'Para achar um bem rápido, use a busca no topo da tela (nome, série, plaqueta ou responsável) ou o botão "Ler QR Code" no celular.'],
         dicas=['Tudo o que é feito fica registrado no histórico do bem, com nome, data e hora.',
                'O sistema funciona no celular: dá para consultar a ficha e conferir o inventário pela câmera.']),
    dict(id='cadastrar-bem', modulo='Bens', titulo='Cadastrar um bem', resumo='Do zero: identificação, convênio, valor, local, responsável e foto.',
         quem='Operador e Administrador', endpoint='cadastrar_bem', rotulo='Abrir o cadastro de bem',
         passos=['Vá em <b>Bens patrimoniais → Cadastrar bem</b>.',
                 '<b>Identificação</b>: nome do bem, categoria, coordenação responsável (opcional), descrição, marca, modelo e número de série. Se o bem não tem série ou está ilegível, escolha a opção e explique.',
                 '<b>Plaqueta</b>: se o bem já tem plaqueta (de inventários anteriores), marque "Sim" e informe o número e a origem: o número de patrimônio sai dela (PA 010 vira 0010). Se não tem, deixe "Não possui": depois de salvar, a ficha terá o botão para gerar o próximo número da sequência.',
                 '<b>Aquisição</b>: escolha o convênio que pagou, a data, o valor e, se tiver, o número e o arquivo da nota fiscal (PDF ou foto).',
                 '<b>Este item é patrimônio?</b> Escolha <b>Sim</b> ou <b>Não</b>. Regra do NGI ICMBio Carajás: item permanente de valor <b>igual ou superior a R$ 250,00</b> é patrimônio. O sistema mostra a sugestão pelo valor; se escolher diferente da regra, explique o motivo.',
                 '<b>Localização</b>: escolha a base/local, a sala e o responsável pelo bem.',
                 'Anexe uma <b>foto</b> (no celular, dá para tirar na hora) e clique em <b>Salvar cadastro</b>.'],
         dicas=['Para mudar local ou responsável depois, use Movimentações: assim o sistema gera o termo de entrega.',
                'Bem antigo sem nota ou sem valor? Preencha a justificativa e siga em frente.',
                'Não cadastre de novo um bem que veio do SIGAD: use Entradas do SIGAD → Tombar.']),
    dict(id='plaquetas', modulo='Bens', titulo='Plaqueta e QR Code', resumo='Número de patrimônio, plaqueta com QR Code e impressão em lote.',
         quem='Operador e Administrador', endpoint='plaquetas_lote', rotulo='Abrir Plaquetas',
         passos=['Abra a <b>ficha do bem</b> (clique no nome dele na lista).',
                 'O número de patrimônio tem <b>4 dígitos</b> e é único. Bem com <b>plaqueta antiga</b> (ex.: Inventário 2023): o número sai dela, só com os algarismos. <b>PA 010 vira 0010</b>.',
                 'Bem <b>sem nenhuma plaqueta</b>: no quadro <b>Plaqueta patrimonial</b>, clique em <b>Gerar número de patrimônio</b>. O sistema usa o próximo número depois do maior já existente, e ele não muda mais.',
                 'Clique em <b>Imprimir plaqueta</b> para imprimir a etiqueta com o QR Code e cole no bem, em lugar visível.',
                 'Para imprimir várias de uma vez, use o menu <b>Plaquetas</b>: filtre os bens que precisam de etiqueta, marque e imprima todas de uma vez.',
                 'Se a etiqueta caiu ou estragou, ajuste "Situação da etiqueta física" no cadastro e reimprima o mesmo número.'],
         dicas=['O QR Code abre a ficha do bem no celular e é usado na conferência do inventário.']),
    dict(id='sigad', modulo='Integração', titulo='Compras do SIGAD (integração)', resumo='Como a compra feita no SIGAD chega aqui e vira bem com plaqueta.',
         quem='SIGAD: Analista/Executor · Patrimônio: Operador e Administrador', endpoint='entradas_sigad', rotulo='Abrir Entradas do SIGAD',
         passos=['<b>No SIGAD</b>, na Compra de Materiais, o painel <b>Patrimônio · itens permanentes</b> mostra quais itens são patrimônio (valor unitário de R$ 250,00 ou mais). O analista pode mudar a classificação, com justificativa.',
                 'Quando a compra estiver <b>Comprado</b> e o material chegar, marque "Confirmo que o material chegou" e clique em <b>Registrar recebimento e enviar ao Patrimônio</b>.',
                 '<b>Aqui no Patrimônio</b>, os itens aparecem em <b>Bens patrimoniais → Entradas do SIGAD</b> (o número ao lado do menu mostra quantos estão esperando). Cada unidade é uma linha: 2 notebooks viram 2 entradas.',
                 'Com o bem em mãos, clique em <b>Tombar</b>. O cadastro abre já preenchido com nome, valor, fornecedor, convênio, coordenação e responsável.',
                 'Complete marca, modelo, <b>número de série</b>, local, foto e salve. A nota fiscal enviada pelo SIGAD é anexada sozinha.',
                 'Na ficha, gere o número de patrimônio, imprima a plaqueta e emita o termo de responsabilidade.',
                 'Se um item não vai virar bem (devolvido ao fornecedor, por exemplo), clique em <b>Descartar</b> e explique o motivo.'],
         dicas=['Se o convênio aparecer em amarelo ("escolher no tombamento"), o nome não bateu entre os dois sistemas: escolha o convênio certo no cadastro e, se quiser, ajuste o nome em Cadastros nos dois sistemas.',
                'Se o SIGAD mostrar erro no envio, use "Tentar enviar de novo" na própria compra: nada é duplicado.']),
    dict(id='movimentacoes', modulo='Movimentações', titulo='Movimentar, transferir e emprestar', resumo='Mudar de local ou de responsável, entrega temporária, manutenção e devolução.',
         quem='Operador e Administrador', endpoint='movimentacoes', rotulo='Abrir Movimentações',
         passos=['Vá em <b>Movimentações → Nova movimentação</b> (ou use o botão na ficha do bem).',
                 'Escolha o local de origem e busque o bem.',
                 'Escolha o tipo: <b>Transferência de responsável</b> (o bem passa para outra pessoa), <b>Remanejamento interno</b> (muda de local/sala), <b>Entrega temporária</b> (empréstimo com previsão de retorno) ou <b>Manutenção</b>.',
                 'Informe o local de destino, o responsável que vai receber, o contato (de preferência o e-mail) e o motivo. Salve.',
                 'A movimentação fica <b>Pendente</b> até a entrega física. Depois de entregar, abra a movimentação e clique em <b>Confirmar entrega</b>.',
                 'Ao confirmar, o cadastro do bem é atualizado e o sistema gera o <b>Termo de movimentação</b>, que pode ser enviado para aceite por e-mail.',
                 'Quando um bem emprestado ou em manutenção voltar, use <b>Registrar devolução</b>.'],
         dicas=['Exemplo: o notebook estava com o João, que saiu do projeto. Faça uma Transferência de responsável para a nova pessoa e confirme a entrega: o termo novo sai na hora.',
                'Empréstimos atrasados aparecem destacados na página inicial.']),
    dict(id='termos', modulo='Documentos', titulo='Termos e aceite eletrônico', resumo='Emitir termo de responsabilidade, termo com vários bens e enviar para aceite.',
         quem='Operador e Administrador', endpoint='documentos', rotulo='Abrir Termos e documentos',
         passos=['Vá em <b>Termos e documentos → Emitir documento</b>.',
                 'Busque o bem e escolha o tipo: <b>Termo de responsabilidade</b> (entrega do bem a uma pessoa) ou <b>Relatório de ocorrência</b> (dano, defeito, sumiço).',
                 'Escreva a justificativa e salve. O documento fica com número, data e código de integridade.',
                 'Para a pessoa aceitar sem precisar de login, abra o documento, informe o nome e o e-mail dela e clique em <b>Enviar para aceite</b>. Ela recebe um link, lê o termo e aceita.',
                 'Quando ela aceitar, o termo mostra <b>Aceito eletronicamente</b>, com data, hora e comprovante.',
                 'Assinatura de quem emitiu: no quadro <b>Assinatura do emitente</b>, marque a declaração, digite de novo a sua senha e clique em <b>Assinar eletronicamente</b>. A linha em branco do termo vira o carimbo <b>Emitido e assinado eletronicamente</b>. Só quem emitiu ou um Administrador pode assinar, e uma única vez.',
                 'A pessoa está com vários bens (notebook, monitor, teclado)? Use <b>Termo com vários bens</b>: um termo só, com um único aceite para todos.',
                 'Se preferir papel, imprima, colha a assinatura e anexe o arquivo assinado no próprio documento.'],
         dicas=['O termo de movimentação é gerado sozinho quando você confirma uma entrega em Movimentações.',
                'Se o e-mail estiver errado, cancele o link e envie de novo.', 'O QR Code no rodapé do termo abre a página de verificação: mostra se o documento é autêntico, quem assinou e quem aceitou, sem mostrar a lista de bens.']),
    dict(id='inventario', modulo='Inventário', titulo='Abrir e conferir o inventário', resumo='Abrir a campanha, conferir os bens, usar o link de campo e encerrar.',
         quem='Operador confere · Administrador encerra', endpoint='inventario', rotulo='Abrir Inventário',
         passos=['Vá em <b>Inventário → Abrir inventário</b>. Dê um nome, escolha o local (ou "Todos os locais"), o convênio se quiser conferir só um, o prazo e a comissão.',
                 'Só existe <b>um inventário aberto por vez</b>. Para várias bases ao mesmo tempo, abra com "Todos os locais" e gere um link de campo para cada base.',
                 'Para conferir, abra o inventário e clique em cada bem: marque <b>Conferido</b>, <b>Divergência</b> (achou, mas algo está diferente) ou <b>Não localizado</b>, e escreva a observação.',
                 'No celular, use <b>Ler QR Code</b>: aponte para a plaqueta e o sistema abre o bem certo na conferência.',
                 '<b>Equipe sem login ou sem internet</b>: na tela do inventário, em "Equipe de campo · sem internet", clique em <b>Gerar link para a equipe</b>, escolha o local e a validade e mande o link pelo WhatsApp. A equipe abre o link uma vez com internet, confere offline e envia quando o sinal voltar.',
                 'Bens encontrados que não estavam na lista aparecem em "Encontrados fora da lista" para você cadastrar depois.',
                 'Quando todos os bens estiverem conferidos, o administrador clica em <b>Encerrar inventário</b>. Os resultados ficam guardados e alimentam os indicadores.'],
         dicas=['Faça o inventário com a lista impressa como apoio: há opção de imprimir na tela do inventário.',
                'Não localizados e divergências precisam de apuração: use Movimentações ou Processos de baixa para resolver cada caso.']),
    dict(id='encerramento', modulo='Encerramento e baixa', titulo='Encerramento do convênio e relatório final', resumo='Destinar os bens no fim do convênio e emitir o relatório final em PDF e Excel.',
         quem='Administrador · Gestor de convênio consulta', endpoint='encerramento_convenios', rotulo='Abrir Encerramento e baixa',
         passos=['Vá em <b>Encerramento e baixa</b> e escolha o convênio.',
                 'A tela mostra todos os bens comprados com o convênio: situação, local, responsável, nota fiscal e último inventário.',
                 'Para cada bem, clique em <b>Registrar destinação</b> e informe o que será feito com ele e o documento ou processo que autoriza.',
                 'Quando estiver tudo certo, baixe o <b>Relatório final (PDF)</b> para assinar e o <b>Relatório final (Excel)</b> para conferência e prestação de contas.'],
         dicas=['O relatório traz os termos emitidos, os inventários e os bens com pendência: resolva as pendências antes de fechar o convênio.']),
    dict(id='baixa', modulo='Encerramento e baixa', titulo='Processo de baixa', resumo='Tirar um bem do acervo: inservível, doação, extravio, furto e outros.',
         quem='Operador solicita · Administrador decide', endpoint='baixas', rotulo='Abrir Processos de baixa',
         passos=['Vá em <b>Encerramento e baixa → Processos de baixa → Solicitar baixa</b>.',
                 'Busque o bem e escolha o motivo: inservível (ocioso, recuperável, antieconômico ou irrecuperável), doação, transferência externa, devolução ao proprietário, extravio, furto/roubo ou outro.',
                 'Informe o processo/referência, a destinação proposta e anexe os documentos (laudo, boletim de ocorrência, termo de doação etc.).',
                 'O processo fica <b>Em análise</b>. O administrador abre o processo e, em <b>Registrar decisão</b>, conclui, indefere ou cancela, informando a autoridade e o documento de autorização.',
                 'Concluída a baixa, o bem sai do acervo ativo, mas o histórico completo continua guardado.'],
         dicas=['Extravio e furto precisam de apuração antes da baixa: registre a ocorrência e anexe os documentos.']),
    dict(id='relatorios', modulo='Relatórios', titulo='Relatórios e indicadores', resumo='Dashboard, indicadores de gestão, relatório de registros, CSV e PDF.',
         quem='Administrador', endpoint='relatorios', rotulo='Abrir Relatórios',
         passos=['Vá em <b>Relatórios</b>. São três abas: <b>Dashboard patrimonial</b>, <b>Indicadores de gestão</b> e <b>Relatório de registros</b>.',
                 'No dashboard, filtre por convênio, local, categoria ou situação. Clique nos resultados para ver os bens.',
                 'Em indicadores, veja acurácia do inventário, não localizados, bens parados e cobertura de termos. Cada indicador explica o que mede e como é calculado.',
                 'Em relatório de registros, escolha bens, movimentações, baixas ou conferências e o período.',
                 'Use <b>Baixar PDF</b> para um relatório pronto para imprimir ou <b>Exportar CSV</b> para abrir no Excel.'],
         dicas=['O relatório final de cada convênio fica em Encerramento e baixa.']),
    dict(id='cadastros', modulo='Cadastros', titulo='Cadastros e usuários', resumo='Locais, convênios, categorias, coordenações e usuários.',
         quem='Operador e Administrador · Usuários só Administrador', endpoint='cadastros', rotulo='Abrir Cadastros',
         passos=['Em <b>Cadastros</b>, mantenha as listas usadas no cadastro dos bens: <b>Locais</b> (bases e escritórios), <b>Convênios</b>, <b>Categorias</b> e <b>Coordenações</b>.',
                 'Item que não é mais usado? Marque como inativo: ele some das listas novas, mas os registros antigos continuam certos.',
                 'Use nos <b>Convênios</b> e <b>Coordenações</b> o mesmo nome/sigla do SIGAD, para as compras chegarem já identificadas.',
                 '<b>Usuários</b> (administrador): cadastre nome, e-mail e perfil. No perfil <b>Gestor de convênio</b>, marque os convênios que a pessoa acompanha.',
                 'Depois de cadastrar, clique em <b>Enviar link de senha</b> para a pessoa criar a própria senha.'],
         dicas=['Para tirar o acesso de alguém, marque o usuário como Inativo: o histórico do que ele fez continua guardado.']),
]

AJUDA_PERGUNTAS = [
    ('O que é patrimônio e o que é só controle simples?', 'Pela regra do NGI ICMBio Carajás, patrimônio é o item permanente de valor unitário igual ou superior a R$ 250,00: recebe plaqueta, termo e entra no inventário. Abaixo disso, fica só no controle simples. No cadastro, quem cadastra escolhe Sim ou Não; o sistema mostra a sugestão pelo valor e pede justificativa quando a escolha foge da regra.'),
    ('O bem mudou de mãos. Preciso cadastrar de novo?', 'Não. Faça uma Movimentação do tipo "Transferência de responsável" e confirme a entrega. O cadastro é atualizado e o termo novo é gerado.'),
    ('A pessoa não consegue aceitar o termo.', 'Confira se o e-mail está certo e se o link não venceu. Se precisar, cancele o envio no documento e envie de novo.'),
    ('Posso conferir o inventário sem internet?', 'Sim. Gere um link de campo na tela do inventário. A equipe abre uma vez com internet e depois confere offline; os registros ficam guardados no celular até enviar.'),
    ('Um bem do SIGAD não apareceu em Entradas do SIGAD.', 'Confira no SIGAD se o recebimento foi registrado e se o item está classificado como patrimônio. Se aparecer erro no envio, use "Tentar enviar de novo" na compra.'),
    ('Errei um cadastro. Como corrijo?', 'Abra a ficha do bem e clique em Editar. A alteração fica no histórico. Local e responsável mudam por Movimentações.'),
    ('Os dados estão seguros?', 'Sim. O acesso é por perfil, tudo fica registrado no histórico e o sistema faz uma cópia de segurança completa todos os dias, guardada fora do servidor.'),
]

OP_TEMPLATES['ajuda'] = r"""<div class="list-heading"><div><h1>Central de ajuda</h1><p>Passo a passo de cada parte do sistema. Para os conceitos (o que é tombamento, termo, inventário), veja o <a href="{{ url_for('guia_patrimonial') }}">Guia patrimonial</a>.</p></div></div>
<section class="panel"><div class="aj-busca"><label class="visually-hidden" for="aj-q">Buscar na ajuda</label><input id="aj-q" type="search" placeholder="O que você quer fazer? Ex.: termo, inventário, SIGAD, plaqueta…" autocomplete="off"></div>
<h2 style="font-size:15px;margin:0 0 8px">O caminho de um bem no sistema</h2>
<div class="aj-fluxo">{% for alvo, rotulo in [('sigad','Compra no SIGAD'),('cadastrar-bem','Cadastro / tombamento'),('plaquetas','Plaqueta'),('termos','Termo de responsabilidade'),('movimentacoes','Movimentações'),('inventario','Inventário'),('encerramento','Encerramento do convênio'),('baixa','Baixa')] %}<a href="#{{ alvo }}" data-aj-abrir="{{ alvo }}">{{ rotulo }}</a>{% if not loop.last %}<span class="seta">→</span>{% endif %}{% endfor %}</div></section>
<div class="aj-grade" id="aj-grade">{% for t in topicos_ajuda %}<a class="aj-card" href="#{{ t.id }}" data-aj-abrir="{{ t.id }}" data-aj-texto="{{ (t.titulo ~ ' ' ~ t.resumo ~ ' ' ~ t.modulo ~ ' ' ~ t.passos|join(' ') ~ ' ' ~ t.dicas|join(' '))|striptags|lower }}"><small>{{ t.modulo }}</small><strong>{{ t.titulo }}</strong><span>{{ t.resumo }}</span></a>{% endfor %}</div>
<div style="margin-top:18px" id="aj-lista">{% for t in topicos_ajuda %}<details class="aj-topico" id="{{ t.id }}" data-aj-texto="{{ (t.titulo ~ ' ' ~ t.resumo ~ ' ' ~ t.modulo ~ ' ' ~ t.passos|join(' ') ~ ' ' ~ t.dicas|join(' '))|striptags|lower }}"><summary><div><h2>{{ t.titulo }}</h2><p>{{ t.resumo }}</p></div></summary><div class="aj-corpo"><span class="aj-quem">Quem faz: {{ t.quem }}</span><ol class="aj-passos">{% for p in t.passos %}<li>{{ p|safe }}</li>{% endfor %}</ol>{% if t.dicas %}<div class="aj-dicas"><strong>Dicas</strong><ul>{% for d in t.dicas %}<li>{{ d|safe }}</li>{% endfor %}</ul></div>{% endif %}{% if pode_acessar(t.endpoint) %}<a class="btn primary aj-ir" href="{{ url_for(t.endpoint) }}">{{ t.rotulo }} →</a>{% endif %}</div></details>{% endfor %}
<p class="aj-vazio" id="aj-vazio" hidden>Nada encontrado. Tente outra palavra, como "termo", "inventário" ou "plaqueta".</p></div>
<section class="panel aj-faq" id="perguntas"><h2>Perguntas frequentes</h2>{% for p, r in perguntas_ajuda %}<details data-aj-texto="{{ (p ~ ' ' ~ r)|lower }}"><summary>{{ p }}</summary><p>{{ r }}</p></details>{% endfor %}</section>
<script>(()=>{const q=document.getElementById('aj-q'),vazio=document.getElementById('aj-vazio');
const sem=t=>t.normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase();
function abrir(id){const d=document.getElementById(id);if(d){d.open=true;d.scrollIntoView({behavior:'smooth',block:'start'});}}
document.querySelectorAll('[data-aj-abrir]').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();abrir(a.dataset.ajAbrir);history.replaceState(null,'','#'+a.dataset.ajAbrir);}));
q.addEventListener('input',()=>{const termo=sem(q.value.trim());let achou=0;
document.querySelectorAll('#aj-lista .aj-topico, #aj-grade .aj-card, .aj-faq details').forEach(el=>{const ok=!termo||sem(el.dataset.ajTexto||'').includes(termo);el.hidden=!ok;if(ok&&el.classList.contains('aj-topico'))achou++;if(el.tagName==='DETAILS'&&termo)el.open=ok;});
vazio.hidden=achou>0;});
if(location.hash)abrir(location.hash.slice(1));})();</script>"""


@app.get('/ajuda')
@login_obrigatorio
def central_ajuda():
    return render_template_string(TEMPLATE, bem=None, formulario=False, modulo_page=True, modulo='ajuda', modulo_template='ajuda',
                                  modulo_titulo='Central de ajuda', op_form=False, topicos_ajuda=AJUDA_TOPICOS,
                                  perguntas_ajuda=AJUDA_PERGUNTAS, **contexto_painel())


ENDPOINTS_RELATORIOS = frozenset({'relatorios','dashboard_bens','exportar_dashboard','indicadores_gestao','exportar_indicadores',
    'exportar_dashboard_pdf','exportar_relatorio_pdf','exportar_indicadores_pdf',
    'relatorio_operacional','exportar_relatorio','exportar_encerramento','relatorio_final_pdf','relatorio_final_xlsx'})
ENDPOINTS_ADMIN = ENDPOINTS_RELATORIOS | frozenset({'usuarios_cadastro','editar_usuario',
    'enviar_link_usuario','decidir_baixa','encerrar_inventario','operacao_sistema'})
ENDPOINTS_CONSULTA = frozenset({'inicio','listar_bens','ficha','foto_bem','nota_fiscal_bem',
    'leitor_qr','guia_patrimonial','central_ajuda','login','logout','esqueci_senha',
    'redefinir_senha','app_manifest','app_icon','app_service_worker','identidade_visual','static'})
PERFIS = ('Consulta', 'Gestor de convênio', 'Operador', 'Administrador')
ENDPOINTS_GESTOR = ENDPOINTS_CONSULTA | frozenset({'encerramento_convenios', 'encerramento_detalhe',
    'relatorio_final_pdf', 'relatorio_final_xlsx'})
ENDPOINTS_PUBLICOS = frozenset({'login','logout','esqueci_senha','redefinir_senha','aceite_termo','verificar_documento','campo_coleta','campo_enviar','campo_sw','sigad_receber',
    'app_manifest','app_icon','app_service_worker','identidade_visual','static','health','prontidao'})

def pode_acessar(endpoint):
    usuario = getattr(g,'usuario',None)
    if not usuario:
        return endpoint in ENDPOINTS_PUBLICOS
    if usuario.perfil == 'Administrador':
        return True
    if usuario.perfil == 'Gestor de convênio':
        return endpoint in ENDPOINTS_GESTOR
    if endpoint in ENDPOINTS_ADMIN:
        return False
    if usuario.leitura:
        return endpoint in ENDPOINTS_CONSULTA
    return usuario.perfil == 'Operador'

app.jinja_env.globals['pode_acessar'] = pode_acessar

# Sentry é opcional: sem DSN não envia nada. Nenhum formulário, token, URL,
# e-mail, foto, parâmetros SQL ou variáveis locais é encaminhado.
def filtrar_evento_monitoramento(evento, hint):
    seguro = {k:evento[k] for k in ('event_id','timestamp','platform','level','release','environment') if k in evento}
    valores = []
    for exc in evento.get('exception',{}).get('values',[]):
        frames = [{k:f[k] for k in ('filename','function','module','lineno','in_app') if k in f}
                  for f in exc.get('stacktrace',{}).get('frames',[])]
        valores.append({'type':exc.get('type','Erro'),'value':'Detalhes omitidos para proteger os dados.',
                        'stacktrace':{'frames':frames}})
    if valores:
        seguro['exception'] = {'values':valores}
    else:
        seguro['message'] = 'Falha operacional do Patrimônio Carajás'
    return seguro

MONITORAMENTO_ATIVO = False
if os.environ.get('SENTRY_DSN','').strip():
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    sentry_sdk.init(dsn=os.environ['SENTRY_DSN'].strip(), integrations=[FlaskIntegration()],
        default_integrations=False, send_default_pii=False, include_local_variables=False,
        max_request_body_size='never', traces_sample_rate=0.0, max_breadcrumbs=0,
        release='patrimonio-carajas@1.0', environment=os.environ.get('APP_ENV','production'),
        before_send=filtrar_evento_monitoramento)
    MONITORAMENTO_ATIVO = True

def comunicar_falha(erro):
    if MONITORAMENTO_ATIVO:
        try:
            sentry_sdk.capture_exception(erro)
        except Exception:
            pass  # Uma falha no coletor nunca impede o atendimento.

@app.errorhandler(500)
def falha_inesperada(erro):
    db.session.rollback()
    referencia = secrets.token_hex(6)
    app.logger.error('Falha interna; referência %s; tipo %s',referencia,
        type(getattr(erro,'original_exception',erro)).__name__)
    return Response('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Falha temporária</title>'
        '<body style="font:16px system-ui;padding:32px;color:#15573F"><h1>Não foi possível concluir.</h1>'
        '<p>Tente novamente. Se o problema continuar, informe esta referência ao administrador: '
        + referencia + '</p><a href="/">Voltar ao início</a></body></html>',status=500,mimetype='text/html')

@app.get('/health/ready')
def prontidao():
    # Identificador estável; nunca recebe chave pela URL. Monitor externo usa Bearer.
    token = os.environ.get('MONITOR_TOKEN','')
    recebido = request.headers.get('Authorization','')
    if len(token)<32 or not hmac.compare_digest(recebido,'Bearer '+token):
        abort(404)
    try:
        with db.engine.connect() as conn:
            if conn.dialect.name == 'postgresql':
                conn.execute(text("SET LOCAL statement_timeout='4000ms'"))
            conn.execute(select(Usuario.id).limit(1)).first()
            conn.execute(select(Bem.id).limit(1)).first()
            ultima = conn.execute(select(ExecucaoBackup.concluido_em).where(
                ExecucaoBackup.status=='Enviado').order_by(ExecucaoBackup.concluido_em.desc()).limit(1)).scalar()
        # Estado de backup só é exigido quando a rotina foi explicitamente habilitada.
        if os.environ.get('BACKUP_EXIGIR_DIARIO')=='sim':
            if not ultima or datetime.now(timezone.utc)-ultima.replace(tzinfo=timezone.utc)>timedelta(hours=30):
                return jsonify(status='degradado'),503
        return jsonify(status='ok'),200
    except Exception:
        return jsonify(status='indisponivel'),503

BACKUP_MAGIC = b'NGICARAJAS-BKP1\n'

def chave_backup():
    try:
        valor = base64.b64decode(os.environ.get('BACKUP_KEY',''),validate=True)
        if len(valor)!=32:
            raise ValueError()
        return valor
    except Exception:
        raise ValueError('Configure BACKUP_KEY com uma chave base64 de 32 bytes.') from None

def tabelas_backup():
    return list(db.metadata.sorted_tables)

def assinatura_backup():
    esquema = [(t.name,[(c.name,str(c.type)) for c in t.columns]) for t in tabelas_backup()]
    return hashlib.sha256(json.dumps(esquema,ensure_ascii=True).encode()).hexdigest()

def codificar_backup(valor, coluna):
    if valor is None:
        return None
    if isinstance(coluna.type,LargeBinary):
        return base64.b64encode(bytes(valor)).decode('ascii')
    if isinstance(coluna.type,(DateTime,Date)):
        return valor.isoformat()
    if isinstance(coluna.type,Numeric):
        return str(valor)
    return valor

def decodificar_backup(valor, coluna):
    if valor is None:
        return None
    if isinstance(coluna.type,LargeBinary):
        return base64.b64decode(valor,validate=True)
    if isinstance(coluna.type,DateTime):
        return datetime.fromisoformat(valor)
    if isinstance(coluna.type,Date):
        return date.fromisoformat(valor)
    if isinstance(coluna.type,Numeric):
        return Decimal(valor)
    return valor

class EscritorCifrado:
    def __init__(self, arquivo, cifrador):
        self.arquivo, self.cifrador = arquivo, cifrador
    def write(self, dados):
        self.arquivo.write(self.cifrador.update(dados))
        return len(dados)
    def flush(self):
        self.arquivo.flush()

def criar_backup_cifrado(destino):
    # Snapshot consistente de TODAS as tabelas do schema exclusivo, inclusive
    # fotos/anexos/hashes de senha. Um registro por vez limita o uso de memória.
    key = chave_backup()
    nonce = secrets.token_bytes(12)
    enc = Cipher(algorithms.AES(key),modes.GCM(nonce)).encryptor()
    enc.authenticate_additional_data(BACKUP_MAGIC)
    total = 0
    try:
        with open(destino,'xb') as saida:
            os.chmod(destino,0o600)
            saida.write(BACKUP_MAGIC+nonce)
            with gzip.GzipFile(fileobj=EscritorCifrado(saida,enc),mode='wb',mtime=0) as gz:
                def linha(obj):
                    gz.write((json.dumps(obj,ensure_ascii=True,separators=(',',':'))+'\n').encode())
                with db.engine.connect() as conn:
                    if conn.dialect.name=='postgresql':
                        conn=conn.execution_options(isolation_level='REPEATABLE READ')
                    with conn.begin():
                        if conn.dialect.name=='postgresql':
                            conn.execute(text('SET TRANSACTION READ ONLY'))
                            conn.execute(text("SET LOCAL statement_timeout='300000ms'"))
                        linha({'formato':1,'versao':'3.2','schema':'patrimonio',
                            'assinatura':assinatura_backup(),'criado_em':datetime.now(timezone.utc).isoformat()})
                        contagens={}
                        for tabela in tabelas_backup():
                            n=0
                            result=conn.execution_options(yield_per=1).execute(select(tabela).order_by(*tabela.primary_key.columns))
                            for registro in result.mappings():
                                linha({'tabela':tabela.name,'dados':{c.name:codificar_backup(registro[c.name],c) for c in tabela.columns}})
                                n+=1
                            result.close()
                            contagens[tabela.name]=n
                            total+=n
                        linha({'fim':True,'contagens':contagens,'registros':total})
            saida.write(enc.finalize())
            saida.write(enc.tag)
        return total
    except Exception:
        Path(destino).unlink(missing_ok=True)
        raise

def abrir_backup_validado(origem, destino):
    # Autentica integralmente ANTES de ler ou restaurar qualquer dado.
    key=chave_backup()
    with open(origem,'rb') as entrada:
        if entrada.read(len(BACKUP_MAGIC))!=BACKUP_MAGIC:
            raise ValueError('Arquivo de backup inválido.')
        nonce=entrada.read(12)
        inicio=entrada.tell()
        entrada.seek(0,2)
        tamanho=entrada.tell()-inicio-16
        if tamanho<0:
            raise ValueError('Backup incompleto.')
        entrada.seek(-16,2)
        tag=entrada.read(16)
        entrada.seek(inicio)
        dec=Cipher(algorithms.AES(key),modes.GCM(nonce,tag)).decryptor()
        dec.authenticate_additional_data(BACKUP_MAGIC)
        while tamanho:
            bloco=entrada.read(min(1024*1024,tamanho))
            if not bloco:
                raise ValueError('Backup incompleto.')
            destino.write(dec.update(bloco))
            tamanho-=len(bloco)
        destino.write(dec.finalize())
        destino.seek(0)
    return gzip.GzipFile(fileobj=destino,mode='rb')

def ler_backup(gz):
    cabecalho=json.loads(next(gz))
    if cabecalho.get('formato')!=1 or cabecalho.get('schema')!='patrimonio' or cabecalho.get('assinatura')!=assinatura_backup():
        raise ValueError('Estrutura diferente. Use o app.py da mesma versão do backup.')
    contagens={t.name:0 for t in tabelas_backup()}
    tabelas={t.name:t for t in tabelas_backup()}
    fim=False
    for linha in gz:
        item=json.loads(linha)
        if item.get('fim') is True:
            if item.get('contagens')!=contagens or item.get('registros')!=sum(contagens.values()) or gz.read(1):
                raise ValueError('Contagens inválidas no backup.')
            fim=True
            break
        tabela=tabelas.get(item.get('tabela'))
        if tabela is None or set(item.get('dados',{}))!={c.name for c in tabela.columns}:
            raise ValueError('Registro inválido no backup.')
        dados={c.name:decodificar_backup(item['dados'][c.name],c) for c in tabela.columns}
        contagens[tabela.name]+=1
        yield tabela,dados
    if not fim:
        raise ValueError('Backup sem conclusão.')

def cliente_backup():
    import boto3
    from botocore.config import Config
    obrigatorias=('BACKUP_S3_BUCKET','BACKUP_S3_ACCESS_KEY_ID','BACKUP_S3_SECRET_ACCESS_KEY')
    if any(not os.environ.get(k,'').strip() for k in obrigatorias):
        raise ValueError('Configure o bucket e as credenciais BACKUP_S3_* no Environment.')
    endpoint=os.environ.get('BACKUP_S3_ENDPOINT','').strip() or None
    if endpoint and (urlsplit(endpoint).scheme!='https' or urlsplit(endpoint).username or urlsplit(endpoint).password):
        raise ValueError('BACKUP_S3_ENDPOINT deve ser HTTPS, sem credenciais na URL.')
    return boto3.client('s3',endpoint_url=endpoint,
        aws_access_key_id=os.environ['BACKUP_S3_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['BACKUP_S3_SECRET_ACCESS_KEY'],
        region_name=os.environ.get('BACKUP_S3_REGION','us-east-1'),
        config=Config(connect_timeout=10,read_timeout=60,retries={'max_attempts':3,'mode':'standard'}))

@app.cli.command('backup-chave')
def backup_chave():
    """Gera uma chave NOVA. Guarde-a fora do Render; não substitua a chave de backups existentes."""
    click.echo(base64.b64encode(secrets.token_bytes(32)).decode('ascii'))

@app.cli.command('backup-criar')
@click.option('--arquivo',type=click.Path(dir_okay=False),required=True)
def backup_criar(arquivo):
    """Cria cópia local cifrada. Um arquivo só no Render não é backup externo."""
    try:
        total=criar_backup_cifrado(arquivo)
        click.echo(f'Backup cifrado criado: {total} registros. Transfira para armazenamento externo.')
    except Exception as erro:
        comunicar_falha(erro)
        raise click.ClickException('Backup não criado. Confira chave, destino e conexão; nenhum segredo foi exibido.') from None

@app.cli.command('backup-verificar')
@click.argument('arquivo',type=click.Path(exists=True,dir_okay=False))
def backup_verificar(arquivo):
    """Verifica chave, autenticidade, estrutura e contagens, sem alterar o banco."""
    try:
        with tempfile.TemporaryFile() as tmp:
            with abrir_backup_validado(arquivo,tmp) as gz:
                n=sum(1 for _ in ler_backup(gz))
        click.echo(f'Backup íntegro e compatível: {n} registros. Banco não alterado.')
    except Exception:
        raise click.ClickException('Backup inválido, incompleto, chave incorreta ou estrutura incompatível.') from None

@app.cli.command('backup-enviar')
def backup_enviar():
    """Rotina diária para um Cron Job: cifrar, verificar, enviar e conferir hash do objeto externo."""
    execucao = None
    try:
        cliente = cliente_backup()
        chave_backup()
        execucao = ExecucaoBackup(
            id=secrets.token_hex(16), iniciado_em=datetime.now(timezone.utc), status='Em andamento'
        )
        db.session.add(execucao)
        db.session.commit()
        with tempfile.TemporaryDirectory(prefix='ngi-backup-') as pasta:
            arquivo = Path(pasta) / 'backup.ngibkp'
            total = criar_backup_cifrado(arquivo)
            with tempfile.TemporaryFile() as tmp:
                with abrir_backup_validado(arquivo, tmp) as gz:
                    if sum(1 for _ in ler_backup(gz)) != total:
                        raise ValueError('Contagem divergente.')
            digest_arquivo = hashlib.sha256()
            with arquivo.open('rb') as fonte:
                for bloco in iter(lambda: fonte.read(1024 * 1024), b''):
                    digest_arquivo.update(bloco)
            sha = digest_arquivo.hexdigest()
            objeto = (
                'patrimonio-carajas/'
                + datetime.now(timezone.utc).strftime('%Y/%m/%d/%H%M%S-')
                + execucao.id
                + '.ngibkp'
            )
            bucket = os.environ['BACKUP_S3_BUCKET']
            cliente.upload_file(
                str(arquivo),
                bucket,
                objeto,
                ExtraArgs={'ContentType': 'application/octet-stream', 'Metadata': {'sha256': sha}},
            )
            # Lê o objeto remoto inteiro: metadados/ETag não substituem integridade.
            remoto = cliente.get_object(Bucket=bucket, Key=objeto)
            corpo = remoto['Body']
            verificador = hashlib.sha256()
            bytes_remotos = 0
            try:
                for bloco in iter(lambda: corpo.read(1024 * 1024), b''):
                    verificador.update(bloco)
                    bytes_remotos += len(bloco)
            finally:
                corpo.close()
            if verificador.hexdigest() != sha or bytes_remotos != arquivo.stat().st_size:
                raise ValueError('Verificação remota falhou.')
            execucao.status = 'Enviado'
            execucao.concluido_em = datetime.now(timezone.utc)
            execucao.registros = total
            execucao.tamanho = bytes_remotos
            execucao.sha256 = sha
            execucao.objeto = objeto
            db.session.commit()
        click.echo('Backup cifrado enviado e verificado no armazenamento externo.')
    except Exception as erro:
        db.session.rollback()
        if execucao:
            try:
                execucao = db.session.get(ExecucaoBackup, execucao.id)
                execucao.status = 'Falhou'
                execucao.concluido_em = datetime.now(timezone.utc)
                db.session.commit()
            except Exception:
                db.session.rollback()
        comunicar_falha(erro)
        if MONITORAMENTO_ATIVO:
            sentry_sdk.flush(timeout=5)
        raise click.ClickException(
            'Backup externo não concluído. Confira configuração e disponibilidade do serviço.'
        ) from None

@app.cli.command('backup-restaurar')
@click.argument('arquivo',type=click.Path(exists=True,dir_okay=False))
@click.option('--confirmar-banco-vazio',is_flag=True,required=True)
def backup_restaurar(arquivo,confirmar_banco_vazio):
    """Restauração transacional: SOMENTE em outro banco vazio, com autorização explícita no Environment."""
    if os.environ.get('BACKUP_PERMITIR_RESTAURACAO')!='BANCO_NOVO_VAZIO' or not confirmar_banco_vazio or os.environ.get('ADMIN_PASSWORD'):
        raise click.ClickException('Use um banco novo vazio, sem ADMIN_PASSWORD, e BACKUP_PERMITIR_RESTAURACAO=BANCO_NOVO_VAZIO.')
    try:
        with tempfile.TemporaryFile() as tmp:
            with abrir_backup_validado(arquivo,tmp) as gz:
                # Valida tudo antes de abrir a transação de escrita.
                total=sum(1 for _ in ler_backup(gz))
            tmp.seek(0)
            with gzip.GzipFile(fileobj=tmp,mode='rb') as gz, db.engine.begin() as conn:
                if conn.dialect.name=='postgresql':
                    conn.execute(text('SELECT pg_advisory_xact_lock(739105632)'))
                    nomes=', '.join('patrimonio."'+t.name+'"' for t in tabelas_backup())
                    conn.execute(text('LOCK TABLE '+nomes+' IN ACCESS EXCLUSIVE MODE'))
                if any(conn.execute(select(t).limit(1)).first() is not None for t in tabelas_backup()):
                    raise ValueError('O banco de destino contém registros.')
                referencias_posteriores=[]
                for tabela,dados in ler_backup(gz):
                    dados=dict(dados)
                    referencias={}
                    for coluna in tabela.columns:
                        if dados[coluna.name] is not None and any(f.column.table is tabela for f in coluna.foreign_keys):
                            if not coluna.nullable:
                                raise ValueError('Referência circular não suportada nesta estrutura.')
                            referencias[coluna.name]=dados[coluna.name]
                            dados[coluna.name]=None
                    conn.execute(tabela.insert().values(**dados))
                    if referencias:
                        referencias_posteriores.append((tabela,{c.name:dados[c.name] for c in tabela.primary_key.columns},referencias))
                for tabela,chaves,referencias in referencias_posteriores:
                    atualizacao=tabela.update()
                    for campo,valor in chaves.items():
                        atualizacao=atualizacao.where(tabela.c[campo]==valor)
                    conn.execute(atualizacao.values(**referencias))
                if conn.dialect.name=='postgresql':
                    for tabela in tabelas_backup():
                        for c in tabela.primary_key.columns:
                            if isinstance(c.type,db.Integer):
                                seq=conn.execute(text('SELECT pg_get_serial_sequence(:t,:c)'),{'t':'patrimonio.'+tabela.name,'c':c.name}).scalar()
                                if seq:
                                    maximo=conn.execute(select(func.max(c))).scalar()
                                    conn.execute(text('SELECT setval(CAST(:s AS regclass),:v,:usado)'),{'s':seq,'v':maximo or 1,'usado':maximo is not None})
                # Invalida sessões/tokens antigos após recuperação de desastre.
                conn.execute(Usuario.__table__.update().values(versao_sessao=Usuario.versao_sessao+1))
                conn.execute(RecuperacaoSenha.__table__.update().values(usado_em=int(time.time())))
        click.echo(f'Restauração concluída: {total} registros; sessões antigas invalidadas. Faça o teste funcional no ambiente separado.')
    except Exception:
        raise click.ClickException('Restauração recusada ou falhou. A transação de dados foi revertida; confira banco vazio, chave e versão.') from None

@app.cli.command('monitoramento-testar')
def monitoramento_testar():
    """Envia somente um evento técnico de teste ao Sentry configurado, sem dados pessoais."""
    if not MONITORAMENTO_ATIVO:
        raise click.ClickException('Configure SENTRY_DSN primeiro.')
    comunicar_falha(RuntimeError('Teste técnico de monitoramento'))
    sentry_sdk.flush(timeout=5)
    click.echo('Evento de teste encaminhado. Confira o recebimento e a regra de alerta no Sentry.')

OP_TEMPLATES['operacao_sistema'] = r'''<div class="list-heading"><div><h1>Segurança e operação</h1><p>Configurações técnicas e acompanhamento do backup externo.</p></div></div><section class="panel"><h2>Backup externo</h2><p><strong>{{ 'Configuração preenchida' if backup_configurado else 'Configuração pendente' }}</strong> · {{ 'Rotina diária exigida pelo monitor' if exigir_diario else 'Verificação de atraso ainda não habilitada' }}</p><p>A configuração preenchida não comprova que existe agendamento. O Cron Job deve executar diariamente <code>flask --app app backup-enviar</code>.</p><div class="tablewrap"><table><thead><tr><th>Início</th><th>Resultado</th><th>Registros</th><th>Tamanho</th></tr></thead><tbody>{% for b in backups %}<tr><td>{{ b.iniciado_em|datahora }}</td><td>{{ b.status }}</td><td>{{ b.registros }}</td><td>{{ '%.1f'|format(b.tamanho/1048576) }} MB</td></tr>{% else %}<tr><td colspan="4">Nenhuma execução registrada. Backup automático ainda não comprovado.</td></tr>{% endfor %}</tbody></table></div><p class="hint">Inclui dados, fotos, anexos e usuários do schema patrimônio. Não inclui código-fonte, Environment, outros schemas ou outros sistemas. Guarde a chave fora da hospedagem; sem ela, a cópia não pode ser recuperada. Configure retenção e versionamento no armazenamento externo.</p></section><section class="panel"><h2>Monitoramento</h2><p>Sentry: <strong>{{ 'Habilitado no código; confira os alertas no serviço' if monitoramento else 'Aguardando SENTRY_DSN' }}</strong></p><p>Verificação protegida do banco: <strong>{{ 'Token configurado' if monitor_token else 'Aguardando MONITOR_TOKEN de pelo menos 32 caracteres' }}</strong>.</p><p>Um monitor externo deve consultar <code>/health/ready</code> usando o cabeçalho Authorization: Bearer. Sem monitor e regra de notificação externos, não há alerta de indisponibilidade.</p></section><section class="panel"><h2>Perfis</h2><p><strong>Administrador:</strong> gestão completa, usuários, relatórios, decisões de baixa e encerramento do inventário.</p><p><strong>Operador:</strong> bens, cadastros auxiliares, movimentações, devoluções, conferência, termos e plaquetas. Sem dashboards, exportações gerais ou administração de usuários.</p><p><strong>Consulta:</strong> início, lista e ficha dos bens, QR Code e guia. Sem alteração, inventário operacional ou impressão de plaquetas.</p><h2>Trabalho sem internet</h2><p>Esta versão exige conexão para consultar e salvar. A conferência sem conexão ainda não está habilitada; instalar o aplicativo não elimina essa dependência.</p></section>'''

@app.get('/administracao/operacao')
@login_obrigatorio
def operacao_sistema():
    configurado=all(os.environ.get(k,'').strip() for k in ('BACKUP_KEY','BACKUP_S3_BUCKET','BACKUP_S3_ACCESS_KEY_ID','BACKUP_S3_SECRET_ACCESS_KEY'))
    return tela_operacao('bens','operacao_sistema','Segurança e operação',
        backups=db.session.scalars(select(ExecucaoBackup).order_by(ExecucaoBackup.iniciado_em.desc()).limit(15)).all(),
        backup_configurado=configurado,monitoramento=MONITORAMENTO_ATIVO,
        monitor_token=len(os.environ.get('MONITOR_TOKEN',''))>=32,exigir_diario=os.environ.get('BACKUP_EXIGIR_DIARIO')=='sim')


# Logos da tela de login: arquivos PNG na pasta static/identidade-visual/ do repositório.
PASTA_IDENTIDADE_VISUAL = os.path.join(app.root_path, "static", "identidade-visual")
IDENTIDADES_VISUAIS = ("icmbio", "unidades")
for _nome in IDENTIDADES_VISUAIS:
    if not os.path.isfile(os.path.join(PASTA_IDENTIDADE_VISUAL, _nome + ".png")):
        app.logger.warning("Imagem ausente: static/identidade-visual/%s.png (logo da tela de login).", _nome)


def remover_fundo_branco(bruto):
    """Torna transparente o fundo branco ligado às bordas (logo salva sem transparência)."""
    imagem = Image.open(io.BytesIO(bruto))
    if imagem.mode in ('RGBA', 'LA') and imagem.getchannel('A').getextrema()[0] < 250:
        return bruto
    rgb = imagem.convert('RGB')
    marca = (255, 0, 254)
    largura, altura = rgb.size
    passo = max(1, min(largura, altura) // 60)
    bordas = [(x, y) for x in range(0, largura, passo) for y in (0, altura - 1)]
    bordas += [(x, y) for y in range(0, altura, passo) for x in (0, largura - 1)]
    for ponto in bordas:
        if min(rgb.getpixel(ponto)) >= 235:
            ImageDraw.floodfill(rgb, ponto, marca, thresh=40)
    r, g, b = ImageChops.difference(rgb, Image.new('RGB', rgb.size, marca)).split()
    visivel = ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda v: 255 if v else 0)
    saida_rgba = imagem.convert('RGBA')
    saida_rgba.putalpha(ImageChops.darker(saida_rgba.getchannel('A'), visivel))
    saida = io.BytesIO()
    saida_rgba.save(saida, 'PNG', optimize=True)
    return saida.getvalue()


@lru_cache(maxsize=2)
def bytes_identidade_visual(nome):
    with open(os.path.join(PASTA_IDENTIDADE_VISUAL, nome + ".png"), "rb") as arquivo:
        bruto = arquivo.read()
    try:
        return remover_fundo_branco(bruto)
    except (OSError, ValueError, UnidentifiedImageError):
        return bruto


@app.get('/identidade-visual/<nome>.png')
def identidade_visual(nome):
    if nome not in IDENTIDADES_VISUAIS:
        abort(404)
    try:
        conteudo = bytes_identidade_visual(nome)
    except FileNotFoundError:
        abort(404)
    return Response(conteudo,mimetype='image/png',headers={'Content-Disposition':'inline; filename='+nome+'.png'})

app.jinja_env.globals['hoje_local']=hoje_local
preparar_estrutura()
configurar_admin_environment()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
